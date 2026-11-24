"""Rendering of the answers.

Every format is built from a list of rows and an ordered list of column
keys. One row is a dict and one column is one key of that dict. A command
fills the rows and the columns, and the functions here do the rest.

There are three formats:

- table: a text table for the terminal.
- json: the whole answer as one JSON object.
- csv: the rows as comma separated values.
"""

import csv
import io
import json
from typing import Any, Dict, List, Optional, Sequence

from rich.console import Console
from rich.table import Table

from .config import PROVIDER_KEY_ENV
from .models import ProviderResult, ProviderStatus

# The width of the text table. It is wide enough for a Chinese address.
TABLE_WIDTH = 120

# The text that is shown when there is nothing to show.
NO_RESULTS = "No results."

# The text that is shown for an empty cell.
EMPTY_CELL = "-"


def _is_numeric(rows: List[Dict[str, Any]], column: str) -> bool:
    """Return True when every value of a column is a number."""
    seen = False
    for row in rows:
        value = row.get(column)
        if value is None or value == "":
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        seen = True
    return seen


def _cell(value: Any) -> str:
    """Return one value as text for the table."""
    if value is None:
        return EMPTY_CELL
    if isinstance(value, str):
        return value if value else EMPTY_CELL
    return str(value)


def render_table(
    rows: List[Dict[str, Any]],
    columns: Sequence[str],
    title: Optional[str] = None,
) -> str:
    """Return the rows as a text table.

    A column with only numbers in it is aligned to the right. A column
    with text in it is aligned to the left. An empty list of rows gives
    a short line that says that there are no results.
    """
    if not rows:
        return NO_RESULTS

    numeric = dict((column, _is_numeric(rows, column)) for column in columns)

    table = Table(title=title, header_style="bold", show_edge=False)
    for column in columns:
        justify = "right" if numeric[column] else "left"
        table.add_column(str(column), justify=justify, overflow="fold")

    for row in rows:
        table.add_row(*[_cell(row.get(column)) for column in columns])

    buffer = io.StringIO()
    console = Console(
        file=buffer,
        width=TABLE_WIDTH,
        no_color=True,
        highlight=False,
        soft_wrap=False,
    )
    console.print(table)
    return buffer.getvalue().rstrip("\n")


def render_json(payload: Any) -> str:
    """Return the payload as JSON text.

    The Chinese names stay readable, so ensure_ascii is off.
    """
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str)


def render_csv(rows: List[Dict[str, Any]], columns: Sequence[str]) -> str:
    """Return the rows as comma separated values, with a header row."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(list(columns))
    for row in rows:
        writer.writerow([_cell(row.get(column)) for column in columns])
    return buffer.getvalue().rstrip("\n")


def render_result(
    rows: List[Dict[str, Any]],
    columns: Sequence[str],
    payload: Any,
    fmt: str,
) -> str:
    """Return the answer in one format.

    The format is "table", "json" or "csv". The JSON format uses the
    payload. The other two use the rows and the columns.
    """
    if fmt == "json":
        return render_json(payload)
    if fmt == "csv":
        return render_csv(rows, columns)

    title = None
    if isinstance(payload, dict):
        title = payload.get("title")
    return render_table(rows, columns, title)


def status_detail(result: ProviderResult) -> str:
    """Return the short reason of one provider answer."""
    status = result.status

    if status == ProviderStatus.OK:
        parts = [str(result.channel)]
        if result.cached:
            parts.append("cached")
        parts.append("{0} ms".format(result.elapsed_ms))
        return ", ".join(parts)
    if status == ProviderStatus.NOT_CONFIGURED:
        return "no {0}".format(PROVIDER_KEY_ENV.get(result.provider, "API key"))
    if status == ProviderStatus.NOT_SUPPORTED:
        return "the channel cannot do this"
    if status == ProviderStatus.RATE_LIMITED:
        return "the rate limit was hit"
    if status == ProviderStatus.TIMEOUT:
        return "the request timed out"
    return result.error or "the request failed"


def render_status_line(results: Dict[str, ProviderResult]) -> str:
    """Return one line that says what every provider did.

    The line looks like this:

        baidu: ok (direct, 142 ms) | amap: not_configured (no AMAP_API_KEY)

    A provider that is rate limited is not the same as a provider with no
    results, so the status is always spelled out. An answer that came from
    the cache says so.
    """
    parts: List[str] = []
    for name in results:
        result = results[name]
        parts.append("{0}: {1} ({2})".format(name, result.status, status_detail(result)))
    return " | ".join(parts)


def render_verbose_details(results: Dict[str, ProviderResult]) -> str:
    """Return the extra lines of the verbose mode.

    Every provider gets one line. It holds the channel, the time, the
    number of attempts, the place the answer came from and the quota
    headers of the answer, when there are any.
    """
    lines: List[str] = []
    for name in results:
        result = results[name]
        line = "{0}: channel {1}, {2} ms, {3} attempt(s)".format(
            name, result.channel, result.elapsed_ms, result.attempts
        )
        if result.cached:
            line += ", from the cache"
        elif result.attempts == 0:
            # No request was made, so nothing came from the network.
            line += ", no request was made"
        else:
            line += ", from the network"
        if result.quota:
            line += ", quota " + ", ".join(
                "{0}={1}".format(key, result.quota[key]) for key in sorted(result.quota)
            )
        lines.append(line)
    return "\n".join(lines)


def render_status_payload(results: Dict[str, ProviderResult]) -> Dict[str, Any]:
    """Return the provider answers as data, for the JSON output."""
    payload: Dict[str, Any] = {}
    for name in results:
        result = results[name]
        payload[name] = {
            "status": str(result.status),
            "channel": str(result.channel),
            "elapsed_ms": result.elapsed_ms,
            "attempts": result.attempts,
            "cached": result.cached,
            "quota": result.quota or {},
            "detail": status_detail(result),
            "error": result.error,
        }
    return payload
