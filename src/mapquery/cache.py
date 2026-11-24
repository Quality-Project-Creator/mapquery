"""A small disk cache for provider answers.

The cache stores JSON files in a folder. The file name is a hash, so no
key ever appears on disk. Secret looking fields are removed before a
value is written.
"""

import hashlib
import json
import os
import re
import tempfile
import threading
import time
from typing import Any, Dict, Optional

# The default cache folder.
DEFAULT_CACHE_DIR = "~/.cache/mapquery"

# The default lifetime of a cached answer, in seconds.
DEFAULT_TTL_SECONDS = 3600.0

# The lock that guards the writes. It is shared by every cache, so two
# threads never write the same file at the same time.
WRITE_LOCK = threading.Lock()

# Field names that must never be written to disk.
SECRET_FIELDS = frozenset(
    {
        "key",
        "ak",
        "sk",
        "sig",
        "signature",
        "secret",
        "token",
        "appkey",
        "appsecret",
        "password",
    }
)

# The names a secret can have in a query string. A reply that echoes the
# request url is scrubbed with this list.
SECRET_QUERY_NAMES = frozenset(
    {
        "key",
        "ak",
        "sk",
        "sig",
        "signature",
        "secret",
        "token",
        "appkey",
        "appsecret",
        "password",
    }
)

# What replaces a secret that was found in a string.
MASKED_VALUE = "masked"


def cache_key(provider: str, channel: str, method: str, params: Dict[str, Any]) -> str:
    """Return the hash of one request. The same request always gives the same hash."""
    blob = json.dumps(
        {
            "provider": provider,
            "channel": channel,
            "method": method,
            "params": params,
        },
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _scrub(value: Any) -> Any:
    """Return the value without any secret looking field or value.

    A field whose name looks like a secret is dropped. A string that
    holds a secret in a query string, such as a reply that echoes the
    request url, has the value replaced.
    """
    if isinstance(value, dict):
        clean = {}
        for name, item in value.items():
            if str(name).lower() in SECRET_FIELDS:
                continue
            clean[name] = _scrub(item)
        return clean
    if isinstance(value, (list, tuple)):
        return [_scrub(item) for item in value]
    if isinstance(value, str):
        return _scrub_string(value)
    return value


def _scrub_string(text: str) -> str:
    """Return the string without the secret looking parts of it."""
    if "=" not in text:
        return text
    names = "|".join(sorted(SECRET_QUERY_NAMES))
    pattern = re.compile(r"([?&])(" + names + r")=([^&\s]*)", re.IGNORECASE)
    return pattern.sub(r"\1\2=" + MASKED_VALUE, text)


class Cache:
    """A small file cache. It can be turned off with the enabled flag."""

    def __init__(
        self,
        cache_dir: Optional[str] = None,
        ttl: float = DEFAULT_TTL_SECONDS,
        enabled: bool = True,
    ) -> None:
        """Set the folder, the lifetime in seconds, and the on or off flag."""
        self.cache_dir = os.path.expanduser(cache_dir or DEFAULT_CACHE_DIR)
        self.ttl = float(ttl)
        self.enabled = bool(enabled)

    def path_for(self, key: str) -> str:
        """Return the file path of one cache key."""
        return os.path.join(self.cache_dir, str(key) + ".json")

    def get(self, key: str) -> Optional[Any]:
        """Return the cached value. Return None when there is nothing to use."""
        if not self.enabled:
            return None

        try:
            with open(self.path_for(key), "r", encoding="utf-8") as handle:
                record = json.load(handle)
        except (OSError, ValueError):
            return None

        if not isinstance(record, dict):
            return None

        created = record.get("created")
        if self.ttl > 0 and isinstance(created, (int, float)):
            if (time.time() - created) > self.ttl:
                return None

        return record.get("value")

    def set(self, key: str, value: Any) -> None:
        """Store a value under the given key.

        The value is written to a temporary file in the same folder and
        then moved over the old one. That move is atomic, so a reader
        never sees half a file, and the write is guarded by a lock, so
        two threads never write the same file at the same time.
        """
        if not self.enabled:
            return

        record = {"created": time.time(), "value": _scrub(value)}
        path = self.path_for(key)
        temp_path = ""
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            with WRITE_LOCK:
                handle, temp_path = tempfile.mkstemp(
                    prefix=os.path.basename(path) + ".", suffix=".tmp", dir=self.cache_dir
                )
                with os.fdopen(handle, "w", encoding="utf-8") as stream:
                    json.dump(record, stream, ensure_ascii=False, default=str)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp_path, path)
                temp_path = ""
        except (OSError, TypeError, ValueError):
            pass
        finally:
            if temp_path:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def clear(self) -> None:
        """Remove every file in the cache folder."""
        if not os.path.isdir(self.cache_dir):
            return
        for name in os.listdir(self.cache_dir):
            if name.endswith(".json"):
                try:
                    os.remove(os.path.join(self.cache_dir, name))
                except OSError:
                    pass
