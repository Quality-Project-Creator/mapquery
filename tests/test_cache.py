"""Tests for the small disk cache."""

import json
import os
import time

from mapquery.cache import Cache, cache_key


def _key() -> str:
    """Return a cache key for a simple request."""
    return cache_key("baidu", "direct", "search", {"wd": "tiananmen", "c": "131"})


def test_the_same_request_gives_the_same_key() -> None:
    """The order of the parameters does not change the key."""
    first = cache_key("baidu", "direct", "search", {"wd": "x", "c": "131"})
    second = cache_key("baidu", "direct", "search", {"c": "131", "wd": "x"})
    assert first == second


def test_a_value_can_be_stored_and_read(tmp_path) -> None:
    """A stored value comes back the same."""
    cache = Cache(cache_dir=str(tmp_path), ttl=60.0)
    key = _key()

    assert cache.get(key) is None
    cache.set(key, {"content": []})
    assert cache.get(key) == {"content": []}


def test_an_old_value_is_not_used(tmp_path) -> None:
    """A value that is too old is treated as missing."""
    cache = Cache(cache_dir=str(tmp_path), ttl=60.0)
    key = _key()

    path = tmp_path / (key + ".json")
    path.write_text(
        json.dumps({"created": time.time() - 3600, "value": {"content": []}}),
        encoding="utf-8",
    )

    assert cache.get(key) is None


def test_a_disabled_cache_stores_nothing(tmp_path) -> None:
    """The off switch stops both the read and the write."""
    cache = Cache(cache_dir=str(tmp_path), enabled=False)
    key = _key()

    cache.set(key, {"content": []})
    assert cache.get(key) is None
    assert not os.listdir(str(tmp_path))


def test_secret_fields_are_not_stored(tmp_path) -> None:
    """A field that holds a key never reaches the disk."""
    cache = Cache(cache_dir=str(tmp_path))
    key = _key()

    cache.set(key, {"key": "secret-value", "content": [{"ak": "secret", "name": "ok"}]})

    raw = (tmp_path / (key + ".json")).read_text(encoding="utf-8")
    assert "secret" not in raw
    assert cache.get(key) == {"content": [{"name": "ok"}]}


def test_the_cache_write_is_atomic(tmp_path) -> None:
    """Eight threads that write the same key leave a file that can be read.

    The value is written to a temporary file and then moved over the old
    one, so a reader never sees half a file.
    """
    import threading

    cache = Cache(cache_dir=str(tmp_path))
    key = _key()

    def writer(number: int) -> None:
        """Write the same key again and again."""
        for _ in range(10):
            cache.set(key, {"number": number, "text": "x" * 500})

    threads = [threading.Thread(target=writer, args=(number,)) for number in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Only the file of the key is there, no temporary file is left.
    assert [path.name for path in tmp_path.iterdir()] == [key + ".json"]

    record = json.loads((tmp_path / (key + ".json")).read_text(encoding="utf-8"))
    assert "value" in record
    assert record["value"]["number"] in range(8)


def test_a_broken_cache_file_is_ignored(tmp_path) -> None:
    """A file that cannot be read is treated as no answer."""
    cache = Cache(cache_dir=str(tmp_path))
    key = _key()

    (tmp_path / (key + ".json")).write_text("{not json", encoding="utf-8")

    assert cache.get(key) is None


def test_a_reply_that_echoes_the_request_url_is_scrubbed() -> None:
    """A reply that echoes the request url must not keep the key in the cache."""
    from mapquery.cache import _scrub

    body = {
        "status": "1",
        "geocodes": [{"location": "116.397,39.909"}],
        "url_echo": "https://restapi.amap.com/v3/geocode/geo?key=a-made-up-key-value-123456&city=110000",
    }

    clean = _scrub(body)

    assert "a-made-up-key-value-123456" not in str(clean)
    assert "city=110000" in clean["url_echo"]
    assert clean["geocodes"][0]["location"] == "116.397,39.909"
