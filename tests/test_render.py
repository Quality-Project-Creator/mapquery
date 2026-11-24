"""Tests for the rendering of the answers.

No test touches the network.
"""

import csv
import io
import json
from typing import Any, Dict, List

from mapquery.models import Channel, ProviderResult, ProviderStatus
from mapquery.render import (
    render_csv,
    render_json,
    render_result,
    render_status_line,
    render_status_payload,
    render_table,
    render_verbose_details,
)

# A small set of rows to render.
ROWS: List[Dict[str, Any]] = [
    {"provider": "baidu", "name": "天安门", "distance_m": 12.3, "lng": 116.403963},
    {"provider": "amap", "name": "天安门广场", "distance_m": 45.6, "lng": 116.397755},
]

# The columns of the rows, in the order they should be shown.
COLUMNS = ["provider", "name", "distance_m", "lng"]


def test_the_table_holds_every_value() -> None:
    """Every value of every row is in the table."""
    text = render_table(ROWS, COLUMNS)

    assert "provider" in text
    assert "name" in text
    assert "baidu" in text
    assert "天安门" in text
    assert "116.403963" in text


def test_the_table_has_a_title_when_one_is_given() -> None:
    """The title is shown above the table."""
    text = render_table(ROWS, COLUMNS, "Places")

    assert "Places" in text


def test_an_empty_table_says_that_there_is_nothing() -> None:
    """An empty list of rows gives a clear line."""
    text = render_table([], COLUMNS)

    assert "No results" in text


def test_the_json_output_can_be_read_again() -> None:
    """The JSON output is valid JSON and holds the payload."""
    payload = {"command": "search", "results": [{"name": "天安门"}]}

    text = render_json(payload)
    parsed = json.loads(text)

    assert parsed == payload
    # The Chinese names stay readable.
    assert "天安门" in text


def test_the_csv_output_has_a_header_and_the_rows() -> None:
    """The CSV output holds the header and every row."""
    text = render_csv(ROWS, COLUMNS)

    lines = list(csv.reader(io.StringIO(text)))
    assert lines[0] == COLUMNS
    assert len(lines) == 3
    assert lines[1][0] == "baidu"
    assert lines[1][1] == "天安门"


def test_render_result_uses_the_wanted_format() -> None:
    """The format decides what comes out."""
    payload = {"command": "search", "results": []}

    table = render_result(ROWS, COLUMNS, payload, "table")
    as_json = render_result(ROWS, COLUMNS, payload, "json")
    as_csv = render_result(ROWS, COLUMNS, payload, "csv")

    assert "baidu" in table
    assert json.loads(as_json) == payload
    assert as_csv.splitlines()[0] == ",".join(COLUMNS)


def test_the_status_line_says_what_every_provider_did() -> None:
    """The status line holds the status, the channel and the time."""
    results = {
        "baidu": ProviderResult(
            provider="baidu",
            status=ProviderStatus.OK,
            channel=Channel.DIRECT,
            elapsed_ms=142,
        ),
        "amap": ProviderResult(
            provider="amap",
            status=ProviderStatus.NOT_CONFIGURED,
            channel=Channel.DIRECT,
            error="Amap needs the key AMAP_API_KEY for search",
        ),
    }

    text = render_status_line(results)

    assert "baidu: ok (direct, 142 ms)" in text
    assert "amap: not_configured (no AMAP_API_KEY)" in text


def test_a_rate_limited_provider_is_not_a_provider_with_no_results() -> None:
    """A rate limit is shown as a rate limit."""
    results = {
        "tencent": ProviderResult(
            provider="tencent",
            status=ProviderStatus.RATE_LIMITED,
            channel=Channel.DIRECT,
            elapsed_ms=90,
        ),
    }

    text = render_status_line(results)

    assert "rate_limited" in text
    assert "rate limit" in text


def test_a_cached_answer_says_so_in_the_status_line() -> None:
    """An answer that came from the cache is marked."""
    results = {
        "tencent": ProviderResult(
            provider="tencent",
            status=ProviderStatus.OK,
            channel=Channel.DIRECT,
            elapsed_ms=3,
            cached=True,
        ),
    }

    text = render_status_line(results)

    assert "tencent: ok (direct, cached, 3 ms)" in text


def test_a_live_answer_does_not_say_that_it_is_cached() -> None:
    """The normal answer has no cached mark."""
    results = {
        "tencent": ProviderResult(
            provider="tencent",
            status=ProviderStatus.OK,
            channel=Channel.DIRECT,
            elapsed_ms=3,
        ),
    }

    text = render_status_line(results)

    assert "tencent: ok (direct, 3 ms)" in text


def test_the_json_output_holds_the_cached_flag() -> None:
    """The flag is part of the answer of the provider."""
    results = {
        "tencent": ProviderResult(
            provider="tencent",
            status=ProviderStatus.OK,
            channel=Channel.DIRECT,
            elapsed_ms=3,
            attempts=2,
            cached=True,
            quota={"current_qps": "3"},
        ),
    }

    payload = render_status_payload(results)

    assert payload["tencent"]["cached"] is True
    assert payload["tencent"]["attempts"] == 2
    assert payload["tencent"]["quota"]["current_qps"] == "3"


def test_the_verbose_lines_hold_the_facts_of_the_request() -> None:
    """The verbose mode shows the channel, the time and the attempts."""
    results = {
        "tencent": ProviderResult(
            provider="tencent",
            status=ProviderStatus.OK,
            channel=Channel.OFFICIAL,
            elapsed_ms=42,
            attempts=3,
            cached=False,
            quota={"current_qps": "3", "limit_qps": "5"},
        ),
    }

    text = render_verbose_details(results)

    assert "tencent" in text
    assert "channel official" in text
    assert "42 ms" in text
    assert "3 attempt(s)" in text
    assert "from the network" in text
    assert "current_qps=3" in text
