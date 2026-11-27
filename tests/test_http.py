"""Tests for the HTTP layer."""

import threading
import time
from typing import Any, Dict, List, Optional

import pytest

from mapquery.config import Config
from mapquery.http import (
    HttpClient,
    is_good_body,
    ProviderHTTPError,
    RateLimiter,
    RateLimitError,
    is_rate_limited,
    safe_url,
)
from mapquery.models import ProviderError, ProviderStatus


class FakeResponse:
    """A fake HTTP answer."""

    def __init__(self, status_code: int = 200, body: Any = None, headers: Optional[Dict[str, str]] = None) -> None:
        """Store the status, the body and the headers."""
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}
        self.ok = 200 <= status_code < 300

    def json(self) -> Any:
        """Return the body."""
        if self._body is None:
            raise ValueError("no json")
        return self._body


class FakeSession:
    """A session that gives back prepared answers."""

    def __init__(self, responses: List[FakeResponse]) -> None:
        """Keep the answers and count the calls."""
        self.responses = list(responses)
        self.calls: List[Dict[str, Any]] = []

    def get(self, url: str, params: Any = None, headers: Any = None, timeout: Any = None) -> FakeResponse:
        """Return the next prepared answer."""
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        if not self.responses:
            raise AssertionError("no answer left")
        return self.responses.pop(0)


class FakeClient(HttpClient):
    """A client that never touches the network."""

    def __init__(self, responses: List[FakeResponse], **kwargs: Any) -> None:
        """Build a client with a fake session."""
        super().__init__(**kwargs)
        self.fake = FakeSession(responses)

    @property
    def session(self) -> FakeSession:  # type: ignore[override]
        """Return the fake session."""
        return self.fake


def test_rate_limiter_never_goes_over_the_rate() -> None:
    """Twelve calls at twenty per second take at least half a second."""
    limiter = RateLimiter(20.0)

    started = time.monotonic()
    for _ in range(12):
        limiter.acquire()
    elapsed = time.monotonic() - started

    assert elapsed >= 0.5


def test_a_slow_rate_waits_longer() -> None:
    """A slow provider makes the calls wait."""
    limiter = RateLimiter(5.0)

    started = time.monotonic()
    for _ in range(3):
        limiter.acquire()
    elapsed = time.monotonic() - started

    assert elapsed >= 0.3


def test_rate_limit_body_detection() -> None:
    """The rate limit bodies of the three providers are found."""
    assert is_rate_limited({"status": 120}) is True
    assert is_rate_limited({"infocode": "10003"}) is True
    assert is_rate_limited({"status": 0}) is False


def test_more_rate_limit_bodies_are_found() -> None:
    """Every known rate limit code is found."""
    assert is_rate_limited({"status": 4}) is True
    assert is_rate_limited({"infocode": "10004"}) is True
    assert is_rate_limited({"infocode": "10009"}) is True
    assert is_rate_limited({"infocode": "10021"}) is True
    assert is_rate_limited({"infocode": "10029"}) is True
    assert is_rate_limited({"status": "1", "info": "OK"}) is False
    assert is_rate_limited("not a dict") is False
    assert is_rate_limited(None) is False


def test_safe_url_hides_the_query() -> None:
    """The query string is dropped, so a key in it stays out of messages."""
    url = "https://apis.map.qq.com/ws/place/v1/suggestion?key=secret-value&keyword=x"
    assert safe_url(url) == "https://apis.map.qq.com/ws/place/v1/suggestion"
    assert "secret" not in safe_url(url)


@pytest.fixture(autouse=True)
def _no_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the retry backoff instant, so the tests stay fast."""
    monkeypatch.setattr(HttpClient, "_backoff", lambda self, attempt: 0.0)


def _client(responses: List[FakeResponse]) -> FakeClient:
    """Return a client that gives back the prepared answers."""
    return FakeClient(responses, config=Config(retries=2))


def test_a_good_answer_is_returned() -> None:
    """A normal answer comes back as parsed JSON."""
    client = _client([FakeResponse(200, {"status": 0, "data": []})])

    data = client.get_json("https://example.com/x")

    assert data == {"status": 0, "data": []}
    assert len(client.fake.calls) == 1


def test_a_429_is_retried() -> None:
    """A 429 is tried again and the second answer is used."""
    client = _client([FakeResponse(429), FakeResponse(200, {"status": 0})])

    data = client.get_json("https://example.com/x")

    assert data == {"status": 0}
    assert len(client.fake.calls) == 2


def test_a_429_that_keeps_coming_raises_a_rate_limit_error() -> None:
    """A rate limit that never ends gives a rate limit error."""
    client = _client([FakeResponse(429), FakeResponse(429), FakeResponse(429)])

    with pytest.raises(RateLimitError) as info:
        client.get_json("https://example.com/x")

    assert info.value.status == ProviderStatus.RATE_LIMITED
    assert len(client.fake.calls) == 3


def test_a_provider_rate_limit_body_is_retried() -> None:
    """A body that says the rate is too high is tried again."""
    client = _client([FakeResponse(200, {"status": 120}), FakeResponse(200, {"status": 0})])

    data = client.get_json("https://example.com/x")

    assert data == {"status": 0}
    assert len(client.fake.calls) == 2


def test_a_server_error_is_retried_and_then_reported() -> None:
    """A 500 is tried again. It is not a rate limit."""
    client = _client([FakeResponse(500), FakeResponse(500), FakeResponse(500)])

    with pytest.raises(ProviderHTTPError) as info:
        client.get_json("https://example.com/x")

    assert info.value.status == ProviderStatus.ERROR
    assert len(client.fake.calls) == 3


def test_a_bad_request_is_not_retried() -> None:
    """A 400 is a user mistake, so it is not tried again."""
    client = _client([FakeResponse(400)])

    with pytest.raises(ProviderHTTPError):
        client.get_json("https://example.com/x")

    assert len(client.fake.calls) == 1


def test_an_answer_that_is_not_json_is_reported() -> None:
    """A page that is not JSON gives a clear error."""
    client = _client([FakeResponse(200, None)])

    with pytest.raises(ProviderHTTPError):
        client.get_json("https://example.com/x")


def test_a_key_never_shows_up_in_an_error_message() -> None:
    """The key is not part of the message when something goes wrong."""
    client = _client([FakeResponse(400)])
    params = {"key": "secret-value", "keyword": "tiananmen"}

    with pytest.raises(ProviderHTTPError) as info:
        client.get_json("https://apis.map.qq.com/ws/place/v1/suggestion", params=params)

    assert "secret-value" not in str(info.value)
    assert "keyword" not in str(info.value)


def test_the_retry_after_header_wins_over_the_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Retry-After header is used as the wait time."""
    client = _client([FakeResponse(429, headers={"Retry-After": "7"}), FakeResponse(200, {})])
    waits: List[float] = []

    def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr("mapquery.http.time.sleep", fake_sleep)

    client.get_json("https://example.com/x")

    assert waits == [7.0]



def test_a_good_body_is_recognised() -> None:
    """Only a body that holds data is worth keeping."""
    assert is_good_body({"status": 0}) is True
    assert is_good_body({"status": "1"}) is True
    assert is_good_body({"results": []}) is True
    assert is_good_body({"status": 240}) is False
    assert is_good_body({"status": "0"}) is False
    # A body that is not an object holds no map data, such as the HTML page
    # that the proxy of Amap answers with. It must not be kept.
    assert is_good_body("not a dict") is False


def test_the_v4_rate_limit_codes_are_found() -> None:
    """The v4 API of Amap reports the quota in errcode."""
    for code in ("10003", "10004", "10009", "10021", "10029"):
        assert is_rate_limited({"errcode": code}) is True
    assert is_rate_limited({"errcode": 10003}) is True
    # A code that is not a quota code is not a rate limit.
    assert is_rate_limited({"errcode": 10001}) is False
    assert is_rate_limited({"errcode": 0}) is False


def test_the_v4_error_body_is_not_kept_in_the_cache() -> None:
    """A v4 body with a non zero errcode is a failure of the provider."""
    body = {"errcode": 10003, "errmsg": "QUQPS_HAS_EXCEEDED_THE_LIMIT"}

    assert is_good_body(body) is False
    # The good v4 body is worth keeping.
    assert is_good_body({"errcode": 0, "errmsg": "OK", "data": {"paths": []}}) is True


def test_the_v4_error_body_is_not_cached(tmp_path) -> None:
    """A v4 failure must never be replayed from the cache."""
    from mapquery.cache import Cache

    cache = Cache(cache_dir=str(tmp_path), ttl=60.0)
    body = {"errcode": 10004, "errmsg": "QUQPS_HAS_EXCEEDED_THE_LIMIT"}
    client = _client([FakeResponse(200, body) for _ in range(3)])
    client.cache = cache

    # The quota code of the v4 API is a rate limit, so it is tried again.
    with pytest.raises(RateLimitError):
        client.get_json("https://example.com/x")

    assert list(tmp_path.iterdir()) == []


def test_a_v4_failure_is_not_cached(tmp_path) -> None:
    """A v4 body that is a failure is not kept in the cache."""
    from mapquery.cache import Cache

    cache = Cache(cache_dir=str(tmp_path), ttl=60.0)
    client = _client(
        [FakeResponse(200, {"errcode": 10001, "errmsg": "INVALID_USER_KEY"})]
    )
    client.cache = cache

    client.get_json("https://example.com/x")

    assert list(tmp_path.iterdir()) == []


def test_an_amap_body_without_geocodes_is_not_cached(tmp_path) -> None:
    """A v3 body that says it worked but holds nothing is not kept.

    The provider would then say that it found no place, and that answer
    would be replayed from the cache for an hour.
    """
    from mapquery.cache import Cache

    cache = Cache(cache_dir=str(tmp_path), ttl=60.0)
    client = _client(
        [
            FakeResponse(
                200,
                {"status": "1", "info": "OK", "infocode": "10000", "count": "0"},
            )
        ]
    )
    client.cache = cache

    client.get_json("https://example.com/x")

    assert list(tmp_path.iterdir()) == []


def test_an_amap_body_with_an_empty_list_is_not_cached(tmp_path) -> None:
    """A v3 body whose geocode list is empty holds nothing."""
    from mapquery.cache import Cache

    cache = Cache(cache_dir=str(tmp_path), ttl=60.0)
    client = _client(
        [
            FakeResponse(
                200,
                {
                    "status": "1",
                    "info": "OK",
                    "infocode": "10000",
                    "count": "0",
                    "geocodes": [],
                },
            )
        ]
    )
    client.cache = cache

    client.get_json("https://example.com/x")

    assert list(tmp_path.iterdir()) == []


def test_the_good_bodies_of_the_providers_are_still_good() -> None:
    """The other providers keep their good bodies."""
    # A Baidu official body with results.
    assert is_good_body({"status": 0, "result": [{"name": "天安门"}]}) is True
    # A Tencent body.
    assert is_good_body({"status": 0, "data": [{"title": "天安门"}]}) is True
    # An Amap v3 body with geocodes.
    assert (
        is_good_body(
            {
                "status": "1",
                "info": "OK",
                "infocode": "10000",
                "count": "1",
                "geocodes": [{"formatted_address": "北京市东城区天安门广场"}],
            }
        )
        is True
    )
    # An Amap v3 route body.
    assert (
        is_good_body(
            {
                "status": "1",
                "info": "OK",
                "infocode": "10000",
                "count": "1",
                "route": {"paths": [{"distance": "1066"}]},
            }
        )
        is True
    )


def test_the_cache_gives_the_same_answer_twice(tmp_path) -> None:
    """A repeated request is answered from the cache."""
    from mapquery.cache import Cache

    cache = Cache(cache_dir=str(tmp_path), ttl=60.0)
    client = _client([FakeResponse(200, {"status": 0, "data": []})])
    client.cache = cache

    first = client.get_json("https://example.com/x")
    second = client.get_json("https://example.com/x")

    assert first == second
    # The second answer came from the cache, so there was only one call.
    assert len(client.fake.calls) == 1


def test_a_failure_of_the_provider_is_not_cached(tmp_path) -> None:
    """A body that holds a failure is not kept in the cache."""
    from mapquery.cache import Cache

    cache = Cache(cache_dir=str(tmp_path), ttl=60.0)
    client = _client([FakeResponse(200, {"status": 240})])
    client.cache = cache

    client.get_json("https://example.com/x")

    assert list(tmp_path.iterdir()) == []


def test_the_baidu_web_failure_body_is_not_cached(tmp_path) -> None:
    """The body of the Baidu web route with result.error is not kept.

    The web route has no top level status. Its failure marker is
    result.error, so such a body must not be replayed later as a good
    answer with no rows.
    """
    from mapquery.cache import Cache

    cache = Cache(cache_dir=str(tmp_path), ttl=60.0)
    client = _client(
        [
            FakeResponse(
                200,
                {"content": None, "result": {"error": -1}, "message": "internal error"},
            )
        ]
    )
    client.cache = cache

    client.get_json("https://example.com/x")

    assert list(tmp_path.iterdir()) == []


def test_a_result_error_of_zero_is_a_good_body() -> None:
    """A web route answer without an error is worth keeping."""
    assert is_good_body({"content": [], "result": {"error": 0}}) is True
    assert is_good_body({"content": None, "result": {"error": -1}}) is False
    assert is_good_body({"result": {"type": 35, "wd": "天安门"}}) is True


def test_the_client_remembers_the_attempts_and_the_cache(tmp_path) -> None:
    """The facts of the request are kept for the result of the provider."""
    from mapquery.cache import Cache

    cache = Cache(cache_dir=str(tmp_path), ttl=60.0)
    client = _client([FakeResponse(200, {"status": 0, "data": []})])
    client.cache = cache

    client.get_json("https://example.com/x", provider="baidu")
    state = client.state_for("baidu")
    assert state["attempts"] == 1
    assert state["cached"] is False

    # The second answer comes from the cache.
    client.get_json("https://example.com/x", provider="baidu")
    state = client.state_for("baidu")
    assert state["cached"] is True
    assert len(client.fake.calls) == 1


def test_a_cached_answer_made_no_request(tmp_path) -> None:
    """A cached answer has zero attempts, because no request was made."""
    from mapquery.cache import Cache

    cache = Cache(cache_dir=str(tmp_path), ttl=60.0)
    client = _client([FakeResponse(200, {"status": 0, "data": []})])
    client.cache = cache

    client.get_json("https://example.com/x", provider="baidu")
    answer = client.request_json("https://example.com/x", provider="baidu")

    assert answer.cached is True
    assert answer.attempts == 0
    assert client.state_for("baidu")["attempts"] == 0
    # Only the first call really went out.
    assert len(client.fake.calls) == 1


def test_the_quota_headers_are_kept(tmp_path) -> None:
    """The quota headers of the answer are kept for the result."""
    client = _client(
        [FakeResponse(200, {"status": 0}, headers={"current_qps": "3", "limit_qps": "5"})]
    )

    client.get_json("https://example.com/x", provider="tencent")

    assert client.state_for("tencent")["quota"]["current_qps"] == "3"


def test_the_quota_of_the_tencent_header_is_read() -> None:
    """Tencent sends the whole quota in one header."""
    client = _client(
        [
            FakeResponse(
                200,
                {"status": 0},
                headers={"X-Limit": "current_qps=3; limit_qps=500; current_pv=98974"},
            )
        ]
    )

    client.get_json("https://example.com/x", provider="tencent")

    quota = client.state_for("tencent")["quota"]
    assert quota["current_qps"] == "3"
    assert quota["limit_qps"] == "500"
    assert quota["current_pv"] == "98974"


def test_a_lost_connection_is_retried() -> None:
    """A connection error is tried again, the same way a timeout is."""
    import requests

    class BrokenSession(FakeSession):
        """A session whose first call breaks."""

        def get(self, url: str, params: Any = None, headers: Any = None, timeout: Any = None) -> FakeResponse:
            """Break once and then answer."""
            self.calls.append({"url": url, "params": params, "timeout": timeout})
            if len(self.calls) == 1:
                raise requests.ConnectionError("the connection broke")
            return self.responses.pop(0)

    client = FakeClient([FakeResponse(200, {"status": 0})], config=Config(retries=2))
    client.fake = BrokenSession([FakeResponse(200, {"status": 0})])

    data = client.get_json("https://example.com/x")

    assert data == {"status": 0}
    assert len(client.fake.calls) == 2


def test_a_lost_connection_that_keeps_coming_is_reported() -> None:
    """A connection that never comes back is an error."""
    import requests

    class BrokenSession(FakeSession):
        """A session that always breaks."""

        def get(self, url: str, params: Any = None, headers: Any = None, timeout: Any = None) -> FakeResponse:
            """Break every time."""
            self.calls.append({"url": url, "params": params, "timeout": timeout})
            raise requests.ConnectionError("the connection broke")

    client = FakeClient([], config=Config(retries=2))
    client.fake = BrokenSession([])

    with pytest.raises(ProviderError) as info:
        client.get_json("https://example.com/x")

    assert info.value.status == ProviderStatus.ERROR
    assert len(client.fake.calls) == 3


def test_the_request_has_a_connect_and_a_read_timeout() -> None:
    """The plan asks for a short connect timeout and a longer read timeout."""
    client = _client([FakeResponse(200, {"status": 0})])

    client.get_json("https://example.com/x")

    assert client.fake.calls[0]["timeout"] == (3.1, 10.0)


def test_the_connect_timeout_can_be_changed() -> None:
    """The connect timeout is a setting of the config."""
    client = FakeClient([FakeResponse(200, {"status": 0})], config=Config(connect_timeout=1.5))

    client.get_json("https://example.com/x")

    assert client.fake.calls[0]["timeout"] == (1.5, 10.0)


def test_a_body_that_holds_no_map_data_is_never_kept_in_the_cache() -> None:
    """The pages of a blocked route hold no data, so they are not kept."""
    from mapquery.http import is_good_body

    # The 403 page of the Amap proxy is not even an object.
    assert is_good_body("<!DOCTYPE HTML PUBLIC \"-//IETF//DTD HTML 2.0//EN\">") is False
    assert is_good_body(None) is False
    assert is_good_body([1, 2, 3]) is False

    # The risk control page of Amap is an object but holds no map data.
    assert is_good_body({"rgv587_flag": "sm", "url": "https://id.amap.com/"}) is False

    # The web route of Baidu has no status and holds real data, it is kept.
    assert is_good_body({"content": [{"name": "a place"}], "result": {}}) is True


# ----------------------------------------------------------------------
# The rate limit of every provider
# ----------------------------------------------------------------------


def test_every_provider_has_its_own_limiter() -> None:
    """The limiter of one provider is not the limiter of another.

    The client is shared by every thread of one run, so the limiter of
    a provider is also the limiter of that provider in another thread.
    """
    client = HttpClient(Config())

    baidu = client.limiter("baidu")
    amap = client.limiter("amap")

    assert baidu is not amap
    assert client.limiter("baidu") is baidu
    assert client.limiter("amap") is amap


def test_the_tokens_of_one_provider_do_not_run_out_for_another() -> None:
    """Every provider has its own bucket, so they do not slow each other."""
    client = HttpClient(Config(rate_limits={"baidu": 10.0, "amap": 10.0}))
    baidu = client.limiter("baidu")
    amap = client.limiter("amap")

    for _ in range(3):
        baidu.acquire()

    # The bucket of Baidu is empty now, the bucket of Amap is still full.
    # The tokens are private, so the check reads them directly.
    assert baidu._tokens < 1.0
    assert amap._tokens == amap.burst


def test_the_default_rate_of_every_provider_is_there() -> None:
    """The three providers have the rate that the config asks for."""
    client = HttpClient(Config())

    assert client.limiter("baidu").rate_per_second == 20.0
    assert client.limiter("amap").rate_per_second == 3.0
    assert client.limiter("tencent").rate_per_second == 5.0


def test_the_rate_of_a_limiter_comes_from_the_config() -> None:
    """The rate of a provider is the one of the config file."""
    client = HttpClient(Config(rate_limits={"baidu": 1.5, "amap": 7.0}))

    assert client.limiter("baidu").rate_per_second == 1.5
    assert client.limiter("amap").rate_per_second == 7.0
    # A provider that is not in the config gets the default rate.
    assert client.limiter("tencent").rate_per_second == 5.0


def test_the_limiter_is_shared_by_the_threads_of_one_provider() -> None:
    """Four threads of one provider wait for each other.

    The bucket holds one request, so three of the four threads have to
    wait for the token of the next one. If every thread had its own
    bucket, they would all go out at the same time.
    """
    client = HttpClient(Config(rate_limits={"amap": 8.0}))
    limiter = client.limiter("amap")

    def take() -> None:
        """Take one token of the limiter."""
        limiter.acquire()

    started = time.monotonic()
    threads = [threading.Thread(target=take) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    elapsed = time.monotonic() - started

    # Three waits of about 0.125 seconds each.
    assert elapsed >= 0.30


def test_a_request_waits_for_the_limiter_of_its_provider() -> None:
    """Three calls of one provider take the time of the rate."""
    client = FakeClient(
        [FakeResponse(200, {"status": 0}) for _ in range(3)],
        config=Config(retries=0, rate_limits={"baidu": 10.0}),
    )

    started = time.monotonic()
    for _ in range(3):
        client.get_json("https://example.com/x", provider="baidu")
    elapsed = time.monotonic() - started

    # Two waits of about 0.1 seconds each.
    assert elapsed >= 0.15


def test_a_retry_takes_a_token_of_the_limiter_again() -> None:
    """A retry is a new request, so it waits for the rate too."""
    client = FakeClient(
        [FakeResponse(429), FakeResponse(200, {"status": 0})],
        config=Config(retries=1, rate_limits={"baidu": 10.0}),
    )

    started = time.monotonic()
    client.get_json("https://example.com/x", provider="baidu")
    elapsed = time.monotonic() - started

    assert len(client.fake.calls) == 2
    # The two attempts are two requests, so the second one waited.
    assert elapsed >= 0.08


def test_the_state_of_a_provider_says_how_many_attempts_it_took() -> None:
    """The number of attempts of the last request is kept."""
    client = FakeClient(
        [FakeResponse(429), FakeResponse(200, {"status": 0})],
        config=Config(retries=1),
    )

    client.get_json("https://example.com/x", provider="baidu")

    assert client.state_for("baidu")["attempts"] == 2
