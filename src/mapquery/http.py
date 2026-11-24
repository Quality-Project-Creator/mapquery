"""The shared HTTP layer.

One client for the whole tool. It keeps one session per thread, it limits
the request rate per provider, and it retries with a backoff.

Error messages never contain a full API key.
"""

import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from urllib.parse import urlsplit, urlunsplit

import requests

from .cache import Cache, cache_key
from .config import Config
from .models import ProviderError, ProviderStatus

# A normal desktop browser string. Some providers reject unknown clients.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Amap codes that mean the request rate is too high.
AMAP_RATE_LIMIT_CODES = frozenset({"10003", "10004", "10009", "10021", "10029"})

# The keys of an Amap v3 reply that hold the data of the call.
AMAP_V3_DATA_KEYS = (
    "geocodes",
    "pois",
    "route",
    "districts",
    "lives",
    "forecast",
    "regeocode",
)

# The keys that every reply of the Amap v3 API carries, apart from the
# status. A reply that has them but holds no data found nothing.
AMAP_V3_MARKER_KEYS = ("info", "infocode", "count")

# Tencent uses status 120 for a rate limit.
TENCENT_RATE_LIMIT_STATUS = 120

# Baidu uses status 4 for a rate limit.
BAIDU_RATE_LIMIT_STATUS = 4

# The first backoff wait, in seconds.
BASE_BACKOFF = 0.5

# The longest backoff wait, in seconds.
MAX_BACKOFF = 8.0

# The extra random part of a backoff wait, in seconds.
JITTER = 0.25

# The longest wait we take from a Retry-After header, in seconds.
MAX_RETRY_DELAY = 60.0


def is_rate_limited(body: Any) -> bool:
    """Return True when the JSON body says the provider is rate limiting.

    Tencent uses status 120. Amap uses infocode 10003, 10004, 10009,
    10021 or 10029. The v4 API of Amap reports the same family of codes
    in errcode. Baidu uses status 4.
    """
    if not isinstance(body, dict):
        return False

    status = body.get("status")
    if status is not None:
        status_text = str(status)
        if status_text in (str(TENCENT_RATE_LIMIT_STATUS), str(BAIDU_RATE_LIMIT_STATUS)):
            return True

    infocode = body.get("infocode")
    if infocode is not None and str(infocode) in AMAP_RATE_LIMIT_CODES:
        return True

    errcode = body.get("errcode")
    if errcode is not None and str(errcode) in AMAP_RATE_LIMIT_CODES:
        return True

    return False


def is_good_body(body: Any) -> bool:
    """Return True when the body holds data and not a failure of the provider.

    Amap uses status "1" for a good answer. Baidu and Tencent use status 0.
    Any other number is a failure of the provider, so such a body is not
    worth keeping in the cache.

    The v4 API of Amap reports a failure with a non zero errcode, so such
    a body is not kept either.

    A reply that says the call worked but holds nothing is not kept
    either. The provider would then say that it found nothing, and that
    answer would be replayed from the cache for an hour.

    The web route of Baidu has no top level status. Its failure marker is
    result.error, so a body with a non zero error inside result is a
    failure too.

    A body that is not an object at all, such as the HTML page that the
    proxy of Amap answers with, holds no data and is never kept.

    The risk control page of Amap is an object, but it carries the marker
    rgv587_flag and no map data, so it is not kept either.
    """
    if not isinstance(body, dict):
        return False

    if "rgv587_flag" in body:
        # This is the risk control reply of Amap. It holds no map data.
        return False

    if _result_error_is_failure(body):
        return False

    if "errcode" in body:
        # This is the v4 shape of Amap. Only errcode 0 is a good answer.
        return _errcode_is_zero(body["errcode"])

    status = body.get("status")
    if status is None:
        return True

    if isinstance(status, bool):
        return False
    if isinstance(status, int):
        return status == 0

    if str(status) != "1":
        return False

    # The string "1" is the good status of the v3 API of Amap.
    return not _amap_v3_holds_nothing(body)


def _errcode_is_zero(errcode: Any) -> bool:
    """Return True when the errcode of a v4 reply means a good answer."""
    try:
        return float(str(errcode)) == 0.0
    except (TypeError, ValueError):
        return False


def _amap_v3_holds_nothing(body: Dict[str, Any]) -> bool:
    """Return True when an Amap v3 reply says it worked but holds no data.

    Amap answers with the string "1" when the call worked. A reply that
    holds no place, no route and no district is a call that found
    nothing, so it must not be kept in the cache.
    """
    has_data = False
    for key in AMAP_V3_DATA_KEYS:
        if key not in body:
            continue
        value = body[key]
        if value is None:
            return True
        if isinstance(value, (list, dict, str, tuple)) and len(value) == 0:
            return True
        has_data = True

    if has_data:
        return False

    # The reply names the fields of a call, such as the count, but it
    # holds no data at all.
    return any(key in body for key in AMAP_V3_MARKER_KEYS)


def _result_error_is_failure(body: Dict[str, Any]) -> bool:
    """Return True when the result of the body holds a failure.

    The web route of Baidu answers with result.error, for example -1, when
    the request failed. A zero error means that the request was fine.
    """
    result = body.get("result")
    if not isinstance(result, dict):
        return False
    if "error" not in result:
        return False

    error = result["error"]
    if error is None:
        return False
    if isinstance(error, bool):
        return error
    if isinstance(error, (int, float)):
        return error != 0
    try:
        return int(str(error).strip()) != 0
    except (TypeError, ValueError):
        return True


def safe_url(url: str) -> str:
    """Return the URL without the query string. Keeps secrets out of messages."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


class RateLimiter:
    """A token bucket. It limits how fast one provider is called."""

    def __init__(self, rate_per_second: float, burst: Optional[float] = None) -> None:
        """Set the rate in requests per second. The burst is the bucket size."""
        self.rate_per_second = float(rate_per_second)
        if burst is None:
            self.burst = 1.0
        else:
            self.burst = max(1.0, float(burst))
        self._tokens = self.burst
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Wait until one request is allowed."""
        if self.rate_per_second <= 0:
            return

        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(
                    self.burst, self._tokens + (now - self._updated) * self.rate_per_second
                )
                self._updated = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self.rate_per_second
            time.sleep(wait)


@dataclass
class JsonResponse:
    """One parsed JSON answer, with a few extra details."""

    data: Any = None
    status_code: int = 0
    quota: Dict[str, Any] = field(default_factory=dict)
    elapsed_ms: int = 0
    attempts: int = 0
    cached: bool = False


class RateLimitError(ProviderError):
    """The provider says the request rate is too high."""

    def __init__(self, message: str) -> None:
        """Mark the error as a rate limit."""
        super().__init__(message, ProviderStatus.RATE_LIMITED)


class ProviderHTTPError(ProviderError):
    """The provider answered with a bad HTTP status."""

    def __init__(self, message: str, status_code: int = 0) -> None:
        """Store the HTTP status code."""
        super().__init__(message, ProviderStatus.ERROR)
        self.status_code = status_code


class HttpClient:
    """A small HTTP client with retries and rate limits."""

    def __init__(
        self,
        config: Optional[Config] = None,
        timeout: Optional[float] = None,
        cache: Optional[Cache] = None,
    ) -> None:
        """Use the given config, or load one from the environment.

        The cache is optional. When there is one, every answer is stored
        in it and a repeated request is answered from the disk.
        """
        self.config = config if config is not None else Config.load()
        self.timeout = timeout if timeout is not None else self.config.timeout
        self.connect_timeout = self.config.connect_timeout
        self.cache = cache
        self._local = threading.local()
        self._limiters: Dict[str, RateLimiter] = {}
        self._lock = threading.Lock()
        self._state: Dict[str, Dict[str, Any]] = {}
        self._state_lock = threading.Lock()

    @property
    def session(self) -> requests.Session:
        """Return one session per thread, so connections are pooled."""
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update(
                {
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                }
            )
            self._local.session = session
        return session

    def limiter(self, provider: str) -> RateLimiter:
        """Return the rate limiter of one provider. Create it on first use."""
        with self._lock:
            limiter = self._limiters.get(provider)
            if limiter is None:
                rate = self.config.rate_limits.get(provider, 5.0)
                limiter = RateLimiter(rate)
                self._limiters[provider] = limiter
            return limiter

    def _remember(
        self,
        provider: Optional[str],
        attempts: int,
        quota: Dict[str, Any],
        cached: bool,
    ) -> None:
        """Keep what happened in the last request of one provider.

        The number of attempts, the quota headers of the answer and the
        flag that says that the answer came from the cache are kept here,
        so the result of the provider can carry them. An answer that came
        from the cache made no request at all, so it has zero attempts.
        """
        if not provider:
            return
        with self._state_lock:
            self._state[provider] = {
                "attempts": int(attempts),
                "quota": dict(quota or {}),
                "cached": bool(cached),
            }

    def state_for(self, provider: str) -> Dict[str, Any]:
        """Return what happened in the last request of one provider."""
        with self._state_lock:
            return dict(self._state.get(provider, {}))

    def get_json(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        referer: Optional[str] = None,
        timeout: Optional[float] = None,
        provider: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        """Fetch a URL and return the parsed JSON body."""
        return self.request_json(
            url,
            params=params,
            referer=referer,
            timeout=timeout,
            provider=provider,
            headers=headers,
        ).data

    def request_json(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        referer: Optional[str] = None,
        timeout: Optional[float] = None,
        provider: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> JsonResponse:
        """Fetch a URL and return the JSON body with a few extra details.

        It retries on a timeout, on a lost connection, on HTTP 429, on HTTP
        5xx and when the provider body says the rate is too high.

        The extra headers are sent with the request. They are used for the
        headers a provider asks for, such as the Origin header of Amap.
        """
        attempts = max(1, self.config.retries + 1)
        read_timeout = timeout if timeout is not None else self.timeout
        # The plan asks for a short connect timeout and a longer read
        # timeout, so the two are given to requests as a pair.
        request_timeout = (self.connect_timeout, read_timeout)
        request_headers: Dict[str, str] = {}
        if referer:
            request_headers["Referer"] = referer
        if headers:
            request_headers.update(headers)

        started = time.monotonic()
        attempt = 0
        http_attempts = 0
        quota: Dict[str, Any] = {}
        cached = False
        try:
            for attempt in range(1, attempts + 1):
                cached_body = self._from_cache(url, params, provider)
                if cached_body is not None:
                    cached = True
                    return JsonResponse(
                        data=cached_body,
                        status_code=200,
                        quota={},
                        elapsed_ms=int((time.monotonic() - started) * 1000),
                        attempts=http_attempts,
                        cached=True,
                    )

                if provider:
                    self.limiter(provider).acquire()

                # The request is really made now, so it is one attempt.
                http_attempts = attempt

                try:
                    response = self.session.get(
                        url, params=params, headers=request_headers, timeout=request_timeout
                    )
                except requests.Timeout:
                    if attempt < attempts:
                        time.sleep(self._backoff(attempt))
                        continue
                    raise ProviderError(
                        "the request timed out for {0}".format(safe_url(url)),
                        ProviderStatus.TIMEOUT,
                    )
                except requests.ConnectionError:
                    # The connection can break for a moment. It is tried
                    # again, the same way a timeout is.
                    if attempt < attempts:
                        time.sleep(self._backoff(attempt))
                        continue
                    raise ProviderError(
                        "the connection failed for {0}".format(safe_url(url)),
                        ProviderStatus.ERROR,
                    )
                except requests.RequestException as exc:
                    # Only the class name is used. The text of the error can hold
                    # the full URL, and the URL can hold the key.
                    raise ProviderError(
                        "the request failed for {0}: {1}".format(safe_url(url), type(exc).__name__)
                    )

                status_code = response.status_code

                if status_code == 429:
                    if attempt < attempts:
                        time.sleep(self._retry_delay(response, attempt))
                        continue
                    raise RateLimitError(
                        "the provider rate limit was hit (HTTP 429) for {0}".format(safe_url(url))
                    )

                if 500 <= status_code < 600:
                    if attempt < attempts:
                        time.sleep(self._retry_delay(response, attempt))
                        continue
                    raise ProviderHTTPError(
                        "the provider server failed (HTTP {0}) for {1}".format(
                            status_code, safe_url(url)
                        ),
                        status_code=status_code,
                    )

                if not response.ok:
                    raise ProviderHTTPError(
                        "the provider answered with HTTP {0} for {1}".format(
                            status_code, safe_url(url)
                        ),
                        status_code=status_code,
                    )

                try:
                    data = response.json()
                except ValueError:
                    raise ProviderHTTPError(
                        "the answer was not JSON for {0}".format(safe_url(url)),
                        status_code=status_code,
                    )

                if is_rate_limited(data):
                    if attempt < attempts:
                        time.sleep(self._retry_delay(response, attempt))
                        continue
                    raise RateLimitError(
                        "the provider rate limit was hit for {0}".format(safe_url(url))
                    )

                elapsed_ms = int((time.monotonic() - started) * 1000)
                quota = _quota_from(response)
                self._to_cache(url, params, provider, data)
                return JsonResponse(
                    data=data,
                    status_code=status_code,
                    quota=quota,
                    elapsed_ms=elapsed_ms,
                    attempts=http_attempts,
                    cached=False,
                )
        finally:
            self._remember(provider, http_attempts, quota, cached)

        raise ProviderError("the request did not run for {0}".format(safe_url(url)))

    def _from_cache(
        self,
        url: str,
        params: Optional[Dict[str, Any]],
        provider: Optional[str],
    ) -> Optional[Any]:
        """Return the cached answer of a request. Return None when there is none."""
        if self.cache is None or not self.cache.enabled:
            return None
        key = cache_key(provider or "", "http", url, dict(params or {}))
        return self.cache.get(key)

    def _to_cache(
        self,
        url: str,
        params: Optional[Dict[str, Any]],
        provider: Optional[str],
        data: Any,
    ) -> None:
        """Store the answer of a request in the cache.

        A body that holds a failure of the provider is not stored, so a
        bad minute does not poison the cache.
        """
        if self.cache is None or not self.cache.enabled:
            return
        if not is_good_body(data):
            return
        key = cache_key(provider or "", "http", url, dict(params or {}))
        self.cache.set(key, data)

    def _backoff(self, attempt: int) -> float:
        """Return the wait time before the next try. It grows and has jitter."""
        base = min(BASE_BACKOFF * (2 ** (attempt - 1)), MAX_BACKOFF)
        return base + random.uniform(0.0, JITTER)

    def _retry_delay(self, response: requests.Response, attempt: int) -> float:
        """Return the wait time. A Retry-After header wins over the backoff."""
        header = response.headers.get("Retry-After")
        if header:
            try:
                return max(0.0, min(float(header), MAX_RETRY_DELAY))
            except ValueError:
                pass
        return self._backoff(attempt)


def _quota_from(response: requests.Response) -> Dict[str, Any]:
    """Return the quota headers of the answer, such as current_qps.

    Tencent sends the whole quota in one header, as
    "current_qps=3; limit_qps=500", so that header is read too.
    """
    quota: Dict[str, Any] = {}
    for name, value in response.headers.items():
        lower = name.lower()
        if lower.startswith("current_") or lower.startswith("limit_"):
            quota[lower] = value
        elif lower.startswith("x-ratelimit-"):
            quota[lower] = value
        elif lower == "x-limit":
            for part in str(value).split(";"):
                if "=" not in part:
                    continue
                key, _, item = part.partition("=")
                key = key.strip().lower()
                item = item.strip()
                if key:
                    quota[key] = item
    return quota
