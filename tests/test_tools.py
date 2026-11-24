"""Tests for the tools of the repository.

The trace script writes the fixtures, so it must never write a full key.
No test here touches the network.
"""

import importlib.util
import os
from typing import Any

# The root of the repository.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The script that records the replies of the providers.
SCRIPT = os.path.join(ROOT, "tools", "trace_sources.py")

# The folder with the recorded replies.
FIXTURES = os.path.join(ROOT, "tests", "fixtures")


def load_script() -> Any:
    """Return the trace script as a module."""
    spec = importlib.util.spec_from_file_location("trace_sources", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_trace_script_hides_the_key_it_knows() -> None:
    """A reply that echoes the key is scrubbed before it is written.

    The 403 page of Amap echoes the request URL, and the URL holds the
    key. The mask lives in the script, so a recorded fixture can never
    hold a full key.
    """
    script = load_script()

    text = script.scrub(
        "http://www.amap.com/_AMapService/v3/place/text?keywords=x&city=110000"
        "&offset=5&key={0}&platform=JS".format(script.AMAP_KEY)
    )

    assert script.AMAP_KEY not in text
    assert "MASKED" in text
    # The rest of the reply is not touched.
    assert "platform=JS" in text


def test_the_trace_script_hides_every_key_of_a_query_string() -> None:
    """Every key of a query string is masked, known or not."""
    script = load_script()

    text = script.scrub("https://example.com/x?key=some-other-key&ak=another-one")

    assert "some-other-key" not in text
    assert "another-one" not in text
    assert "MASKED" in text


def test_the_trace_script_hides_the_key_of_a_json_body() -> None:
    """A key inside a JSON body is masked too."""
    script = load_script()

    text = script.scrub('{"key": "some-other-key", "status": 0}')

    assert "some-other-key" not in text
    assert '"status": 0' in text


def test_no_fixture_holds_a_full_key() -> None:
    """No recorded reply holds a full front-end key."""
    from mapquery.providers.direct_keys import (
        AMAP_FRONTEND_KEY,
        BAIDU_FRONTEND_AK,
        TENCENT_FRONTEND_KEY,
    )

    for name in sorted(os.listdir(FIXTURES)):
        path = os.path.join(FIXTURES, name)
        if not os.path.isfile(path):
            continue
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
        assert AMAP_FRONTEND_KEY not in text, name
        assert BAIDU_FRONTEND_AK not in text, name
        assert TENCENT_FRONTEND_KEY not in text, name


def test_no_document_holds_a_full_key_outside_the_two_allowed_places() -> None:
    """Only the two source files may hold a full front-end key."""
    from mapquery.providers.direct_keys import (
        AMAP_FRONTEND_KEY,
        BAIDU_FRONTEND_AK,
        TENCENT_FRONTEND_KEY,
    )

    allowed = ("direct_keys.py", "trace_sources.py")
    keys = (AMAP_FRONTEND_KEY, BAIDU_FRONTEND_AK, TENCENT_FRONTEND_KEY)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    for folder, _dirs, names in os.walk(root):
        if ".git" in folder or "__pycache__" in folder:
            continue
        for name in names:
            path = os.path.join(folder, name)
            if name in allowed:
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as handle:
                    text = handle.read()
            except OSError:
                continue
            for key in keys:
                assert key not in text, path
