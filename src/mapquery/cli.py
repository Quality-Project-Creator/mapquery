"""The command line interface of mapquery.

Every command that talks to the providers prints one status line, so the
user can see which provider answered, on which channel and how long it
took.

The exit codes are:

- 0: at least one provider answered.
- 1: every provider failed.
- 2: the command was used in the wrong way.
"""

import argparse
import json
import os
import sys
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import __version__
from .cache import Cache
from .compare import compare_places
from .config import DEFAULT_CONFIG_PATH, Config, ConfigFileError, read_config_file
from .coords import CoordSystem, convert, haversine_m
from .engine import run_many
from .http import HttpClient
from .models import (
    Channel,
    Coord,
    GeoResult,
    Place,
    ProviderError,
    ProviderResult,
    ProviderStatus,
    Route,
)
from .providers import PROVIDER_NAMES, get_provider
from .providers.base import FEATURES, Provider
from .render import (
    render_csv,
    render_result,
    render_status_line,
    render_status_payload,
    render_table,
    render_verbose_details,
)

# The coordinate systems of the convert command.
SYSTEMS = ("wgs84", "gcj02", "bd09")

# The route modes of the command and the name that every provider uses.
# The name of the cycling mode is the one of the provider, "bicycling".
ROUTE_MODES: Dict[str, Dict[str, str]] = {
    "driving": {"baidu": "driving", "amap": "driving", "tencent": "driving"},
    "walking": {"baidu": "walking", "amap": "walking", "tencent": "walking"},
    "cycling": {"baidu": "cycling", "amap": "bicycling", "tencent": "bicycling"},
    "transit": {"baidu": "transit", "amap": "transit", "tencent": "transit"},
}

# The keys that every provider has in the config file.
CONFIG_KEYS: Dict[str, Tuple[str, ...]] = {
    "baidu": ("ak", "sk"),
    "amap": ("key", "secret"),
    "tencent": ("key", "sk"),
}

# The text at the top of the config file.
CONFIG_HEADER = """\
# The keys of mapquery.
#
# Every key is optional. Without a key the tool uses the direct channel
# of each provider. That channel needs no account, but it is shared with
# the live website of the provider, so it is rate limited.
#
# A key of your own switches that provider to the official channel. The
# official channel has a better quota and the full feature list.
#
# The keys are also read from the environment. The environment always
# wins over this file:
#
#   BAIDU_MAP_AK      BAIDU_MAP_SK
#   AMAP_API_KEY      AMAP_SECRET_KEY
#   TENCENT_MAP_KEY   TENCENT_MAP_SK
#
# The settings below are optional too.
"""

# The settings that a new config file starts with.
CONFIG_SETTINGS: Dict[str, Any] = {
    "timeout": 10,
    "connect_timeout": 3.1,
    "retries": 2,
    "jobs": 8,
}


class UsageError(Exception):
    """The command was used in the wrong way."""


# ----------------------------------------------------------------------
# The parser
# ----------------------------------------------------------------------


def _global_options() -> argparse.ArgumentParser:
    """Return a parser that holds the options that every command has.

    Every option has no default, so the value of the main parser is kept
    when the option is not used after the command.
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--providers",
        metavar="LIST",
        default=argparse.SUPPRESS,
        help="the providers to call, such as baidu,amap",
    )
    formats = parser.add_mutually_exclusive_group()
    formats.add_argument(
        "--json",
        dest="json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="print the answer as JSON",
    )
    formats.add_argument(
        "--table",
        dest="table",
        action="store_true",
        default=argparse.SUPPRESS,
        help="print the answer as a table",
    )
    formats.add_argument(
        "--csv",
        dest="csv",
        action="store_true",
        default=argparse.SUPPRESS,
        help="print the answer as CSV",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=argparse.SUPPRESS,
        help="how many providers are called at the same time",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=argparse.SUPPRESS,
        help="the timeout of one request in seconds",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=argparse.SUPPRESS,
        help="how many times a failed request is tried again",
    )
    parser.add_argument(
        "--no-cache",
        dest="no_cache",
        action="store_true",
        default=argparse.SUPPRESS,
        help="do not use the local cache",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=argparse.SUPPRESS,
        help="print more about what happens",
    )
    return parser


def build_parser() -> argparse.ArgumentParser:
    """Return the parser of the whole tool."""
    common = _global_options()
    parser = argparse.ArgumentParser(
        prog="mapq",
        parents=[common],
        description=(
            "Query Baidu Maps, Amap and Tencent Maps at the same time "
            "and compare the answers."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version="mapquery {0}".format(__version__),
    )
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    search = commands.add_parser("search", parents=[common], help="search for places")
    search.add_argument("keyword", help="the words to look for")
    search.add_argument("--city", help="the city, such as Beijing")
    search.add_argument("--near", metavar="LNG,LAT", help="a point to measure from")
    search.add_argument("--radius", type=float, help="the radius in metres")
    search.add_argument("--limit", type=int, default=10, help="how many places to show")

    geocode = commands.add_parser(
        "geocode", parents=[common], help="turn an address into a point"
    )
    geocode.add_argument("address", help="the address to look for")
    geocode.add_argument("--city", help="the city, such as Beijing")

    reverse = commands.add_parser(
        "reverse", parents=[common], help="turn a point into an address"
    )
    reverse.add_argument("point", metavar="LNG,LAT", help="the point as lng,lat")

    route = commands.add_parser("route", parents=[common], help="find a route")
    route.add_argument("from_point", metavar="FROM", help="a point or an address")
    route.add_argument("to_point", metavar="TO", help="a point or an address")
    route.add_argument(
        "--mode",
        choices=sorted(ROUTE_MODES.keys()),
        default="driving",
        help="the kind of route",
    )

    matrix = commands.add_parser(
        "matrix", parents=[common], help="straight line distances between points"
    )
    matrix.add_argument(
        "--from",
        dest="from_points",
        required=True,
        metavar="LIST",
        help="the start points, separated by a semicolon",
    )
    matrix.add_argument(
        "--to",
        dest="to_points",
        required=True,
        metavar="LIST",
        help="the end points, separated by a semicolon",
    )

    compare = commands.add_parser(
        "compare", parents=[common], help="compare the answers of the providers"
    )
    compare.add_argument("keyword", help="the words to look for")
    compare.add_argument("--city", help="the city, such as Beijing")
    compare.add_argument("--near", metavar="LNG,LAT", help="a point to measure from")
    compare.add_argument("--radius", type=float, help="the radius in metres")
    compare.add_argument("--limit", type=int, default=10, help="how many places to show")

    convert_parser = commands.add_parser(
        "convert", parents=[common], help="change a point from one system to another"
    )
    convert_parser.add_argument("point", metavar="LNG,LAT", help="the point as lng,lat")
    convert_parser.add_argument(
        "--from",
        dest="from_system",
        choices=SYSTEMS,
        required=True,
        help="the system of the point",
    )
    convert_parser.add_argument(
        "--to", dest="to_system", choices=SYSTEMS, required=True, help="the wanted system"
    )

    district = commands.add_parser(
        "district", parents=[common], help="show the districts of a place"
    )
    district.add_argument("keyword", help="the place to look for")

    weather = commands.add_parser(
        "weather", parents=[common], help="show the weather of an area code"
    )
    weather.add_argument("adcode", help="the area code, such as 110101")

    commands.add_parser(
        "providers", parents=[common], help="show the providers and what they can do"
    )

    config_parser = commands.add_parser(
        "config", parents=[common], help="look at and change the keys"
    )
    config_commands = config_parser.add_subparsers(dest="config_command", metavar="ACTION")
    config_commands.add_parser(
        "show", parents=[common], help="show the effective configuration"
    )
    config_set = config_commands.add_parser(
        "set", parents=[common], help="write one key to the config file"
    )
    config_set.add_argument("provider", choices=list(PROVIDER_NAMES))
    config_set.add_argument("key", help="the name of the key, such as ak or secret")
    config_set.add_argument("value", nargs="?", help="the value of the key")
    config_commands.add_parser(
        "init", parents=[common], help="create the config file"
    )

    return parser


# ----------------------------------------------------------------------
# The settings of one run
# ----------------------------------------------------------------------


class Settings:
    """Everything that one run of the tool needs."""

    def __init__(self, args: argparse.Namespace) -> None:
        """Read the config, the options and the cache."""
        self.config = Config.load()

        jobs = getattr(args, "jobs", None)
        if jobs is not None:
            self.config.jobs = int(jobs)

        timeout = getattr(args, "timeout", None)
        if timeout is not None:
            self.config.timeout = float(timeout)

        retries = getattr(args, "retries", None)
        if retries is not None:
            self.config.retries = int(retries)

        self.verbose = bool(getattr(args, "verbose", False))
        self.no_cache = bool(getattr(args, "no_cache", False))
        self.cache = Cache(self.config.cache_dir, enabled=not self.no_cache)
        self.http = HttpClient(self.config, timeout=self.config.timeout, cache=self.cache)


def _format_of(args: argparse.Namespace) -> str:
    """Return the wanted output format of the command line.

    Only one format can be used. The check is done here as well, so a
    format that is given before the command and one that is given after
    it are caught too.
    """
    chosen = [
        name for name in ("json", "table", "csv") if getattr(args, name, False)
    ]
    if len(chosen) > 1:
        raise UsageError(
            "use only one of --json, --table and --csv, not {0}".format(
                " and ".join("--" + name for name in chosen)
            )
        )
    if chosen:
        return chosen[0]
    return "table"


# ----------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------


def _selected_providers(args: argparse.Namespace) -> List[str]:
    """Return the names of the providers that the user wants.

    The order of the tool is kept, so the output is always the same.
    """
    raw = getattr(args, "providers", None)
    if raw is None:
        return list(PROVIDER_NAMES)

    wanted = []
    for position, part in enumerate(str(raw).split(","), start=1):
        name = part.strip().lower()
        if not name:
            # The list is not empty, one of its entries is. The entry that
            # is wrong is named, so the user knows what to fix.
            raise UsageError(
                "the providers list has an empty entry at position {0}. "
                "Use one of {1}.".format(position, ", ".join(PROVIDER_NAMES))
            )
        if name not in PROVIDER_NAMES:
            raise UsageError(
                "unknown provider: {0}. Use one of {1}.".format(name, ", ".join(PROVIDER_NAMES))
            )
        wanted.append(name)

    return [name for name in PROVIDER_NAMES if name in wanted]


def _text_of(value: Any, what: str) -> str:
    """Return the text of an argument. Raise UsageError when it is empty.

    An empty keyword or an empty address is a mistake of the user, so it
    stops the command before a live call is made.
    """
    text = "" if value is None else str(value).strip()
    if not text:
        raise UsageError("the {0} must not be empty".format(what))
    return text


def _parse_point(text: Any) -> Optional[Coord]:
    """Return a point as a pair of floats.

    Return None when the text is not a point. The order is lng,lat.
    """
    if text is None:
        return None
    parts = str(text).replace(" ", "").split(",")
    if len(parts) != 2:
        return None
    try:
        lng = float(parts[0])
        lat = float(parts[1])
    except ValueError:
        return None
    if not -180.0 <= lng <= 180.0:
        return None
    if not -90.0 <= lat <= 90.0:
        return None
    return (lng, lat)


def _point_of(text: Any, what: str) -> Coord:
    """Return a point. Raise UsageError when the text is not a point."""
    point = _parse_point(text)
    if point is None:
        raise UsageError(
            "{0} must be written as lng,lat, such as 116.397428,39.908823".format(what)
        )
    return point


def _limit_of(args: argparse.Namespace) -> int:
    """Return how many places the user wants."""
    limit = getattr(args, "limit", None)
    if limit is None:
        return 10
    if limit < 1:
        raise UsageError("the limit must be at least 1")
    return int(limit)


def _place_dict(place: Place) -> Dict[str, Any]:
    """Return one place as a dict, for the JSON output."""
    return {
        "name": place.name,
        "address": place.address,
        "lng": place.lng,
        "lat": place.lat,
        "category": place.category,
        "uid": place.uid,
    }


def _geo_dict(result: GeoResult) -> Dict[str, Any]:
    """Return one geo result as a dict, for the JSON output."""
    return {
        "address": result.address,
        "lng": result.lng,
        "lat": result.lat,
        "level": result.level,
    }


def _route_dict(route: Route) -> Dict[str, Any]:
    """Return one route as a dict, for the JSON output."""
    return {
        "provider": route.provider,
        "mode": route.mode,
        "distance_m": route.distance_m,
        "distance_km": route.distance_m / 1000.0,
        "duration_min": route.duration_s / 60.0,
        "origin": {"lng": route.origin[0], "lat": route.origin[1]},
        "destination": {"lng": route.destination[0], "lat": route.destination[1]},
        "steps": route.steps,
    }


# ----------------------------------------------------------------------
# The provider calls
# ----------------------------------------------------------------------


def _make_task(
    provider: Provider,
    feature: str,
    action: Callable[[Provider], Any],
) -> Callable[[], Any]:
    """Return the task of one provider.

    A provider that cannot do the feature on its active channel is not
    called at all. Its answer says why.
    """

    def task() -> Any:
        if not provider.supports(feature):
            error = provider.missing_feature_error(feature)
            return ProviderResult(
                provider=provider.name,
                status=error.status,
                channel=provider.active_channel(),
                data=None,
                error=error.message,
            )
        return action(provider)

    return task


def _call_providers(
    settings: Settings,
    providers: Sequence[str],
    feature: str,
    action: Callable[[Provider], Any],
) -> Dict[str, ProviderResult]:
    """Call every provider at the same time and return the answers.

    The order of the answers is the order of the providers, never the
    order in which the calls finished.
    """
    tasks: Dict[str, Callable[[], Any]] = {}
    channels: Dict[str, Channel] = {}
    for name in providers:
        provider = get_provider(name, settings.config, settings.http)
        tasks[name] = _make_task(provider, feature, action)
        channels[name] = provider.active_channel()
    results = run_many(tasks, jobs=settings.config.jobs, channels=channels)
    _add_http_state(settings, results)
    return results


def _add_http_state(
    settings: Settings,
    results: Dict[str, ProviderResult],
) -> None:
    """Give every result the facts of the request that it needed.

    The number of attempts, the quota headers of the answer and the flag
    that says that the answer came from the cache are known by the http
    layer, so they are copied into the result here.
    """
    for name, result in results.items():
        state = settings.http.state_for(name)
        if not state:
            continue
        if "attempts" in state:
            # An answer that came from the cache made no request, so it
            # has zero attempts. That zero is a fact, so it is copied too.
            result.attempts = int(state["attempts"])
        if state.get("quota"):
            result.quota = dict(state["quota"])
        if state.get("cached"):
            result.cached = True


def _reason_of(result: ProviderResult) -> str:
    """Return the short reason of one provider answer."""
    if result.error:
        return result.error
    return str(result.status)


def _exit_code(results: Dict[str, ProviderResult]) -> int:
    """Return 0 when a provider answered and 1 when none of them did."""
    for result in results.values():
        if result.is_ok:
            return 0
    return 1


def _print_status(args: argparse.Namespace, results: Dict[str, ProviderResult]) -> None:
    """Print the status line and the extra lines of the verbose mode."""
    print(render_status_line(results))
    if getattr(args, "verbose", False):
        print(render_verbose_details(results))


def _finish(
    args: argparse.Namespace,
    rows: List[Dict[str, Any]],
    columns: Sequence[str],
    payload: Dict[str, Any],
    results: Dict[str, ProviderResult],
    exit_code: Optional[int] = None,
) -> int:
    """Print the answer and return the exit code.

    The exit code is 0 when a provider answered and 1 when none of them
    did. A command that has its own rule, like the matrix, gives the code
    that it wants.
    """
    fmt = _format_of(args)

    if fmt == "table":
        _print_status(args, results)
        print("")
        print(render_result(rows, columns, payload, fmt))
        if not rows and not all(result.is_ok for result in results.values()):
            print("No provider could answer with data.")
        return _exit_code(results) if exit_code is None else exit_code

    if fmt == "csv":
        # The CSV goes to the standard output, so the status line goes to
        # the error output. That keeps the file clean.
        print(render_status_line(results), file=sys.stderr)
        if getattr(args, "verbose", False):
            print(render_verbose_details(results), file=sys.stderr)
    elif getattr(args, "verbose", False):
        print(render_status_line(results), file=sys.stderr)
        print(render_verbose_details(results), file=sys.stderr)

    print(render_result(rows, columns, payload, fmt))
    return _exit_code(results) if exit_code is None else exit_code


# ----------------------------------------------------------------------
# The commands
# ----------------------------------------------------------------------


def _cmd_search(args: argparse.Namespace) -> int:
    """Run the search command."""
    settings = Settings(args)
    providers = _selected_providers(args)
    keyword = _text_of(args.keyword, "keyword")
    city = _text_of(args.city, "city") if args.city is not None else None
    limit = _limit_of(args)
    near = _point_of(args.near, "the near point") if args.near else None
    radius = args.radius

    def action(provider: Provider) -> List[Place]:
        return provider.search_places(
            keyword, city=city, near=near, radius=radius, limit=limit
        )

    results = _call_providers(settings, providers, "search", action)

    rows: List[Dict[str, Any]] = []
    for name in providers:
        result = results.get(name)
        if result is None or not result.is_ok:
            continue
        for place in result.data:
            row: Dict[str, Any] = {
                "provider": name,
                "name": place.name,
                "address": place.address,
                "category": place.category or "",
                "lng": round(place.lng, 6),
                "lat": round(place.lat, 6),
            }
            if near is not None:
                row["distance_m"] = round(
                    haversine_m(place.lng, place.lat, near[0], near[1]), 1
                )
            rows.append(row)

    columns = ["provider", "name", "address", "category", "lng", "lat"]
    if near is not None:
        columns.append("distance_m")

    payload = {
        "command": "search",
        "query": {
            "keyword": keyword,
            "city": city,
            "limit": limit,
            "near": list(near) if near else None,
            "radius": radius,
        },
        "providers": render_status_payload(results),
        "results": {
            name: [_place_dict(place) for place in results[name].data]
            for name in providers
            if name in results and results[name].is_ok
        },
    }
    return _finish(args, rows, columns, payload, results)


def _cmd_geocode(args: argparse.Namespace) -> int:
    """Run the geocode command."""
    settings = Settings(args)
    providers = _selected_providers(args)
    address = _text_of(args.address, "address")
    city = _text_of(args.city, "city") if args.city is not None else None

    def action(provider: Provider) -> GeoResult:
        return provider.geocode(address, city=city)

    results = _call_providers(settings, providers, "geocode", action)

    rows: List[Dict[str, Any]] = []
    for name in providers:
        result = results.get(name)
        if result is None or not result.is_ok:
            continue
        rows.append(
            {
                "provider": name,
                "address": result.data.address,
                "lng": round(result.data.lng, 6),
                "lat": round(result.data.lat, 6),
                "level": result.data.level or "",
            }
        )

    columns = ["provider", "address", "lng", "lat", "level"]
    payload = {
        "command": "geocode",
        "query": {"address": address, "city": city},
        "providers": render_status_payload(results),
        "results": {
            name: _geo_dict(results[name].data)
            for name in providers
            if name in results and results[name].is_ok
        },
    }
    return _finish(args, rows, columns, payload, results)


def _cmd_reverse(args: argparse.Namespace) -> int:
    """Run the reverse command."""
    settings = Settings(args)
    providers = _selected_providers(args)
    point = _point_of(args.point, "the point")

    def action(provider: Provider) -> GeoResult:
        return provider.reverse_geocode(point[0], point[1])

    results = _call_providers(settings, providers, "reverse", action)

    rows: List[Dict[str, Any]] = []
    for name in providers:
        result = results.get(name)
        if result is None or not result.is_ok:
            continue
        rows.append(
            {
                "provider": name,
                "address": result.data.address,
                "lng": round(result.data.lng, 6),
                "lat": round(result.data.lat, 6),
                "level": result.data.level or "",
            }
        )

    columns = ["provider", "address", "lng", "lat", "level"]
    payload = {
        "command": "reverse",
        "query": {"lng": point[0], "lat": point[1]},
        "providers": render_status_payload(results),
        "results": {
            name: _geo_dict(results[name].data)
            for name in providers
            if name in results and results[name].is_ok
        },
    }
    return _finish(args, rows, columns, payload, results)


def _resolve_point(provider: Provider, text: str, what: str) -> Coord:
    """Return the point of one end of a route.

    The text is a point, such as "116.397,39.909", or an address. An
    address is geocoded with the same provider. When the provider cannot
    do it, the error says which end of the route failed.

    The status of the error is never changed. A provider that is rate
    limited stays rate limited, a provider that timed out stays a
    timeout.
    """
    point = _parse_point(text)
    if point is not None:
        return point

    try:
        result = provider.geocode(text)
    except ProviderError as exc:
        if exc.status == ProviderStatus.NOT_SUPPORTED:
            raise ProviderError(
                "{0} cannot find an address for {1}".format(provider.display_name, what),
                ProviderStatus.NOT_SUPPORTED,
            )
        raise ProviderError(
            "{0} could not find {1}: {2}".format(provider.display_name, what, exc.message),
            exc.status,
        )
    return (result.lng, result.lat)


def _cmd_route(args: argparse.Namespace) -> int:
    """Run the route command."""
    settings = Settings(args)
    providers = _selected_providers(args)
    mode = args.mode
    from_text = args.from_point
    to_text = args.to_point

    def action(provider: Provider) -> Route:
        origin = _resolve_point(provider, from_text, "the start point")
        destination = _resolve_point(provider, to_text, "the end point")
        provider_mode = ROUTE_MODES.get(mode, {}).get(provider.name, mode)
        return provider.route(origin, destination, mode=provider_mode)

    results = _call_providers(settings, providers, "route", action)

    rows: List[Dict[str, Any]] = []
    routes: List[Route] = []
    for name in providers:
        result = results.get(name)
        if result is None or not result.is_ok:
            continue
        route = result.data
        routes.append(route)
        rows.append(
            {
                "provider": name,
                "mode": route.mode,
                "distance_m": round(route.distance_m, 1),
                "distance_km": round(route.distance_m / 1000.0, 3),
                "duration_min": round(route.duration_s / 60.0, 1),
            }
        )

    columns = ["provider", "mode", "distance_m", "distance_km", "duration_min"]
    payload = {
        "command": "route",
        "query": {"from": from_text, "to": to_text, "mode": mode},
        "providers": render_status_payload(results),
        "results": [_route_dict(route) for route in routes],
    }

    fmt = _format_of(args)
    if fmt == "table":
        _print_status(args, results)
        print("")
        print(render_table(rows, columns))
        _print_steps(routes)
        return _exit_code(results)

    return _finish(args, rows, columns, payload, results)


def _print_steps(routes: List[Route]) -> None:
    """Print the first steps of every route."""
    if not routes:
        return
    print("")
    print("Steps:")
    for route in routes:
        print("  {0} ({1}):".format(route.provider, route.mode))
        if not route.steps:
            print("    no steps came back")
            continue
        for number, step in enumerate(route.steps[:5], start=1):
            instruction = step.get("instruction") or step.get("road") or "step"
            distance = step.get("distance_m", 0.0)
            print("    {0}. {1} ({2:.0f} m)".format(number, instruction, distance))


def _split_points(text: str) -> List[str]:
    """Return the points of a list that is separated by a semicolon."""
    return [part.strip() for part in str(text).split(";") if part.strip()]


def _cmd_matrix(args: argparse.Namespace) -> int:
    """Run the matrix command."""
    settings = Settings(args)
    providers = _selected_providers(args)
    from_texts = _split_points(args.from_points)
    to_texts = _split_points(args.to_points)

    if not from_texts or not to_texts:
        raise UsageError("the matrix needs at least one point on each side")

    # A point that is a number is used as it is. An address is geocoded
    # with a provider that really answers.
    from_points: List[Optional[Coord]] = []
    to_points: List[Optional[Coord]] = []
    for text in from_texts:
        from_points.append(_parse_point(text))
    for text in to_texts:
        to_points.append(_parse_point(text))

    needed = [text for text in from_texts + to_texts if _parse_point(text) is None]

    results: Dict[str, ProviderResult] = {}
    resolved: Dict[str, Coord] = {}
    if needed:
        def action(provider: Provider) -> Any:
            found: List[Optional[Coord]] = []
            failure: Optional[ProviderError] = None
            for text in needed:
                try:
                    result = provider.geocode(text)
                    found.append((result.lng, result.lat))
                except ProviderError as exc:
                    # A provider that fails keeps its own status. It is
                    # never reported as an answer with no data.
                    found.append(None)
                    if failure is None:
                        failure = exc
            if failure is not None:
                return ProviderResult(
                    provider=provider.name,
                    status=failure.status,
                    channel=provider.active_channel(),
                    data=found,
                    error="{0} could not find every place: {1}".format(
                        provider.display_name, failure.message
                    ),
                )
            return found

        results = _call_providers(settings, providers, "geocode", action)

        # Every address is taken from a provider that answered with a point.
        # The providers are tried in turn, so a rate limited provider does
        # not stop the others. The answers of the other providers are still
        # shown in the status line.
        for text in needed:
            for name in providers:
                result = results.get(name)
                if result is None:
                    continue
                points = result.data if isinstance(result.data, list) else []
                point = dict(zip(needed, points)).get(text)
                if point is not None:
                    resolved[text] = point
                    break

        from_points = [
            resolved.get(text, point) for text, point in zip(from_texts, from_points)
        ]
        to_points = [
            resolved.get(text, point) for text, point in zip(to_texts, to_points)
        ]

    rows: List[Dict[str, Any]] = []
    for origin_text, origin in zip(from_texts, from_points):
        row: Dict[str, Any] = {"from": origin_text}
        for destination_text, destination in zip(to_texts, to_points):
            if origin is None or destination is None:
                row[destination_text] = "-"
            else:
                row[destination_text] = round(
                    haversine_m(origin[0], origin[1], destination[0], destination[1]), 1
                )
        rows.append(row)

    columns = ["from"] + to_texts
    payload = {
        "command": "matrix",
        "title": "Straight line distance in metres. This is not a road distance.",
        "query": {"from": from_texts, "to": to_texts},
        "providers": render_status_payload(results),
        "results": rows,
    }

    missing = [text for text in needed if text not in resolved]
    if missing:
        return _matrix_failed(args, rows, columns, payload, results, missing)

    fmt = _format_of(args)
    if fmt == "table":
        if results:
            _print_status(args, results)
            print("")
        print(render_table(rows, columns, payload["title"]))
        # Every place was found, so the matrix is complete.
        return 0

    if results:
        return _finish(args, rows, columns, payload, results, exit_code=0)

    # No address was given, so no provider was called.
    print(render_result(rows, columns, payload, fmt))
    return 0


def _matrix_failed(
    args: argparse.Namespace,
    rows: List[Dict[str, Any]],
    columns: Sequence[str],
    payload: Dict[str, Any],
    results: Dict[str, ProviderResult],
    missing: Sequence[str],
) -> int:
    """Say that no provider could find the places, and stop with the code 1."""
    message = "No provider could find these places: {0}".format(", ".join(missing))

    fmt = _format_of(args)
    if fmt == "table":
        _print_status(args, results)
        print("")
        print(message)
        return 1

    print(render_status_line(results), file=sys.stderr)
    if getattr(args, "verbose", False):
        print(render_verbose_details(results), file=sys.stderr)
    print(message, file=sys.stderr)
    print(render_result(rows, columns, payload, fmt))
    return 1


def _cmd_compare(args: argparse.Namespace) -> int:
    """Run the compare command."""
    settings = Settings(args)
    providers = _selected_providers(args)
    keyword = _text_of(args.keyword, "keyword")
    city = _text_of(args.city, "city") if args.city is not None else None
    limit = _limit_of(args)
    near = _point_of(args.near, "the near point") if args.near else None
    radius = args.radius

    def action(provider: Provider) -> List[Place]:
        return provider.search_places(
            keyword, city=city, near=near, radius=radius, limit=limit
        )

    results = _call_providers(settings, providers, "search", action)

    places: Dict[str, List[Place]] = {}
    skipped: Dict[str, str] = {}
    for name in providers:
        result = results.get(name)
        if result is None:
            continue
        if result.is_ok:
            places[name] = result.data
        else:
            skipped[name] = _reason_of(result)

    comparison = compare_places(places, centre=near, skipped=skipped)

    rows: List[Dict[str, Any]] = []
    for name in providers:
        result = results.get(name)
        if result is None or not result.is_ok:
            continue
        for place in result.data:
            row = {
                "provider": name,
                "name": place.name,
                "address": place.address,
                "lng": round(place.lng, 6),
                "lat": round(place.lat, 6),
            }
            if near is not None:
                row["distance_m"] = round(
                    haversine_m(place.lng, place.lat, near[0], near[1]), 1
                )
            rows.append(row)

    columns = ["provider", "name", "address", "lng", "lat"]
    if near is not None:
        columns.append("distance_m")

    payload = {
        "command": "compare",
        "query": {
            "keyword": keyword,
            "city": city,
            "limit": limit,
            "near": list(near) if near else None,
            "radius": radius,
        },
        "providers": render_status_payload(results),
        "results": comparison,
    }

    fmt = _format_of(args)
    if fmt == "table":
        _print_status(args, results)
        print("")
        print(render_table(rows, columns, "Places"))
        _print_comparison(comparison)
        return _exit_code(results)

    if fmt == "csv":
        # The CSV holds the places, then the clusters, then the consensus.
        csv_columns = list(columns) + ["members", "spread_max_m"]
        csv_rows = _compare_csv_rows(rows, comparison, near)
        print(render_status_line(results), file=sys.stderr)
        if getattr(args, "verbose", False):
            print(render_verbose_details(results), file=sys.stderr)
        print(render_csv(csv_rows, csv_columns))
        return _exit_code(results)

    return _finish(args, rows, columns, payload, results)


def _compare_csv_rows(
    rows: List[Dict[str, Any]],
    comparison: Dict[str, Any],
    near: Optional[Coord],
) -> List[Dict[str, Any]]:
    """Return the places, the clusters and the consensus as rows for the CSV.

    A row that holds [places], [clusters] or [consensus] marks the section
    that comes after it. The cluster rows use the same columns as the
    place rows: the provider column holds the providers of the cluster,
    the point columns hold the centre of the cluster and the two extra
    columns hold the number of places and the largest distance.
    """
    out: List[Dict[str, Any]] = [{"provider": "[places]"}]
    for row in rows:
        out.append(dict(row))

    def cluster_row(cluster: Dict[str, Any]) -> Dict[str, Any]:
        """Return one cluster as a row of the CSV."""
        centre = cluster.get("centre") or {}
        row: Dict[str, Any] = {
            "provider": ", ".join(cluster.get("providers") or []),
            "name": cluster.get("name") or "",
            "address": "",
            "lng": round(float(centre.get("lng") or 0.0), 6),
            "lat": round(float(centre.get("lat") or 0.0), 6),
            "members": len(cluster.get("members") or []),
            "spread_max_m": round(float(cluster.get("spread_max_m") or 0.0), 1),
        }
        if near is not None:
            row["distance_m"] = round(
                haversine_m(row["lng"], row["lat"], near[0], near[1]), 1
            )
        return row

    out.append({"provider": "[clusters]"})
    for cluster in comparison.get("clusters") or []:
        out.append(cluster_row(cluster))

    out.append({"provider": "[consensus]"})
    for cluster in comparison.get("consensus") or []:
        out.append(cluster_row(cluster))

    return out


def _print_comparison(comparison: Dict[str, Any]) -> None:
    """Print the clusters, the consensus and the spread."""
    clusters = comparison.get("clusters", [])
    consensus = comparison.get("consensus", [])
    spread = comparison.get("spread", {})

    cluster_rows: List[Dict[str, Any]] = []
    for cluster in clusters:
        cluster_rows.append(
            {
                "id": cluster["id"],
                "name": cluster["name"],
                "providers": ", ".join(cluster["providers"]),
                "members": len(cluster["members"]),
                "lng": round(cluster["centre"]["lng"], 6),
                "lat": round(cluster["centre"]["lat"], 6),
                "spread_max_m": round(cluster["spread_max_m"], 1),
            }
        )
    print("")
    print(
        render_table(
            cluster_rows,
            ["id", "name", "providers", "members", "lng", "lat", "spread_max_m"],
            "Clusters",
        )
    )

    print("")
    if consensus:
        consensus_rows = [
            {
                "id": cluster["id"],
                "name": cluster["name"],
                "providers": ", ".join(cluster["providers"]),
                "spread_max_m": round(cluster["spread_max_m"], 1),
            }
            for cluster in consensus
        ]
        print(
            render_table(
                consensus_rows,
                ["id", "name", "providers", "spread_max_m"],
                "Consensus",
            )
        )
    else:
        print("Consensus: none. The providers do not agree on a common place.")

    print("")
    print("Spread: {0} clusters with more than one place, max {1:.1f} m, mean {2:.1f} m".format(
        spread.get("count", 0), spread.get("max_m", 0.0), spread.get("mean_m", 0.0)
    ))

    skipped = comparison.get("skipped", {})
    if skipped:
        print("")
        print("Skipped:")
        for name in sorted(skipped):
            print("  {0}: {1}".format(name, skipped[name]))


def _cmd_convert(args: argparse.Namespace) -> int:
    """Run the convert command."""
    point = _point_of(args.point, "the point")
    source = CoordSystem(args.from_system)
    target = CoordSystem(args.to_system)
    lng, lat = convert(point[0], point[1], source, target)

    rows = [
        {
            "from_system": args.from_system,
            "to_system": args.to_system,
            "lng": round(lng, 7),
            "lat": round(lat, 7),
        }
    ]
    columns = ["from_system", "to_system", "lng", "lat"]
    payload = {
        "command": "convert",
        "query": {
            "lng": point[0],
            "lat": point[1],
            "from": args.from_system,
            "to": args.to_system,
        },
        "results": {"lng": lng, "lat": lat},
    }
    fmt = _format_of(args)
    if fmt == "table":
        print(render_table(rows, columns))
        return 0
    print(render_result(rows, columns, payload, fmt))
    return 0


def _cmd_district(args: argparse.Namespace) -> int:
    """Run the district command."""
    settings = Settings(args)
    providers = _selected_providers(args)
    keyword = _text_of(args.keyword, "keyword")

    def action(provider: Provider) -> List[Dict[str, Any]]:
        return provider.district(keyword)

    results = _call_providers(settings, providers, "district", action)

    rows: List[Dict[str, Any]] = []
    for name in providers:
        result = results.get(name)
        if result is None or not result.is_ok:
            continue
        for row in _flatten_districts(name, result.data):
            rows.append(row)

    columns = ["provider", "name", "level", "id"]
    payload = {
        "command": "district",
        "query": {"keyword": keyword},
        "providers": render_status_payload(results),
        "results": rows,
    }
    return _finish(args, rows, columns, payload, results)


def _flatten_districts(provider: str, node: Any, depth: int = 0) -> List[Dict[str, Any]]:
    """Return the flat list of the districts of one provider answer."""
    rows: List[Dict[str, Any]] = []
    if not isinstance(node, dict):
        return rows

    name = node.get("name")
    if isinstance(name, str) and name:
        rows.append(
            {
                "provider": provider,
                "name": name,
                "level": str(node.get("level") if node.get("level") is not None else depth),
                "id": str(node.get("adcode") or node.get("id") or ""),
            }
        )

    for key in ("districts", "children"):
        children = node.get(key)
        if not isinstance(children, list):
            continue
        for child in children:
            rows.extend(_flatten_districts(provider, child, depth + 1))

    return rows


def _cmd_weather(args: argparse.Namespace) -> int:
    """Run the weather command.

    Only Amap can do the weather. The flag of the providers is respected:
    when Amap is not in the list, the command stops and says that the
    selected providers cannot do the weather.
    """
    settings = Settings(args)
    providers = _selected_providers(args)
    adcode = _text_of(args.adcode, "area code")

    if "amap" not in providers:
        print(
            "Only Amap can do the weather. It is not in the selected providers: {0}.".format(
                ", ".join(providers)
            ),
            file=sys.stderr,
        )
        return 2

    def action(provider: Provider) -> Dict[str, Any]:
        return provider.weather(adcode)

    results = _call_providers(settings, ["amap"], "weather", action)

    rows = _weather_rows(results.get("amap"))
    columns = ["provider", "city", "date", "weather", "temperature", "wind", "humidity"]
    payload = {
        "command": "weather",
        "query": {"adcode": adcode},
        "providers": render_status_payload(results),
        "results": rows,
    }

    result = results.get("amap")
    if result is not None and result.status == ProviderStatus.NOT_CONFIGURED:
        print(
            "Amap is not configured. Set AMAP_API_KEY to get the weather.",
            file=sys.stderr,
        )

    return _finish(args, rows, columns, payload, results)


def _weather_rows(result: Optional[ProviderResult]) -> List[Dict[str, Any]]:
    """Return the weather of one provider answer as rows."""
    rows: List[Dict[str, Any]] = []
    if result is None or not result.is_ok:
        return rows
    body = result.data
    if not isinstance(body, dict):
        return rows

    lives = body.get("lives")
    if isinstance(lives, list):
        for item in lives:
            if not isinstance(item, dict):
                continue
            rows.append(_weather_row("amap", item, "today"))

    forecast = body.get("forecast")
    if isinstance(forecast, list):
        for item in forecast:
            if not isinstance(item, dict):
                continue
            for day in item.get("casts", []) or []:
                if isinstance(day, dict):
                    rows.append(_weather_row("amap", day, str(day.get("date") or "")))

    return rows


def _weather_row(provider: str, item: Dict[str, Any], date: str) -> Dict[str, Any]:
    """Return one weather row."""
    return {
        "provider": provider,
        "city": item.get("city") or item.get("adcode") or "",
        "date": date,
        "weather": item.get("weather") or "",
        "temperature": item.get("temperature") or "",
        "wind": item.get("winddirection") or item.get("windpower") or "",
        "humidity": item.get("humidity") or "",
    }


def _cmd_providers(args: argparse.Namespace) -> int:
    """Run the providers command."""
    settings = Settings(args)

    rows: List[Dict[str, Any]] = []
    for name in PROVIDER_NAMES:
        provider = get_provider(name, settings.config, settings.http)
        channel = provider.active_channel()
        key = settings.config.key_for(name)
        row: Dict[str, Any] = {
            "provider": name,
            "name": provider.display_name,
            "channel": str(channel),
            "key": Config.mask_key(key) if key else "not set",
        }
        for feature in FEATURES:
            row[feature] = "yes" if feature in provider.features_for(channel) else "no"
        rows.append(row)

    columns = ["provider", "name", "channel", "key"] + list(FEATURES)
    payload = {
        "command": "providers",
        "results": rows,
    }
    fmt = _format_of(args)
    if fmt == "table":
        print(render_table(rows, columns, "Providers"))
        return 0
    print(render_result(rows, columns, payload, fmt))
    return 0


# ----------------------------------------------------------------------
# The config file
# ----------------------------------------------------------------------


def _config_path() -> str:
    """Return the path of the config file."""
    path = os.environ.get("MAPQUERY_CONFIG") or DEFAULT_CONFIG_PATH
    return os.path.expanduser(path)


def _toml_value(value: Any) -> str:
    """Return one value as a TOML value.

    A string is written as a JSON string. A JSON string is a valid TOML
    basic string, and it escapes the quotes and the backslashes of the
    value, so the file that is written can always be read again.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return (
            "{"
            + ", ".join(
                "{0} = {1}".format(name, _toml_value(item))
                for name, item in value.items()
            )
            + "}"
        )
    return json.dumps(str(value), ensure_ascii=False)


def _write_private_file(path: str, text: str) -> None:
    """Write a file that only the user can read.

    The config file holds the keys, so it never gets the rights of the
    other files of the folder.
    """
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.chmod(path, 0o600)


def _write_config_data(path: str, data: Dict[str, Any]) -> None:
    """Write the data of the config file.

    Every value is written as a TOML value, so the file that is written
    can always be read again. The file holds the keys, so only the user
    can read it.
    """
    folder = os.path.dirname(path) or "."
    if folder and not os.path.isdir(folder):
        os.makedirs(folder, exist_ok=True)

    lines = [CONFIG_HEADER]

    plain = {
        name: value for name, value in data.items() if not isinstance(value, dict)
    }
    if plain:
        for name in sorted(plain):
            lines.append("{0} = {1}".format(name, _toml_value(plain[name])))
        lines.append("")

    for name in sorted(data):
        block = data[name]
        if not isinstance(block, dict):
            continue
        lines.append("[{0}]".format(name))
        for key in sorted(block):
            lines.append("{0} = {1}".format(key, _toml_value(block[key])))
        lines.append("")

    _write_private_file(path, "\n".join(lines).rstrip("\n") + "\n")


def _cmd_config(args: argparse.Namespace) -> int:
    """Run the config command."""
    action = getattr(args, "config_command", None)
    if action == "show":
        return _cmd_config_show(args)
    if action == "set":
        return _cmd_config_set(args)
    if action == "init":
        return _cmd_config_init(args)

    print("Use one of: config show, config set, config init.", file=sys.stderr)
    return 2


def _cmd_config_show(args: argparse.Namespace) -> int:
    """Run the config show command."""
    config = Config.load()
    path = _config_path()

    masked = config.masked_keys()
    values = [
        ("config file", path),
        ("baidu_ak", masked["baidu_ak"] or "not set"),
        ("baidu_sk", masked["baidu_sk"] or "not set"),
        ("amap_key", masked["amap_key"] or "not set"),
        ("amap_secret", masked["amap_secret"] or "not set"),
        ("tencent_key", masked["tencent_key"] or "not set"),
        ("tencent_sk", masked["tencent_sk"] or "not set"),
        ("timeout", str(config.timeout)),
        ("connect_timeout", str(config.connect_timeout)),
        ("retries", str(config.retries)),
        ("jobs", str(config.jobs)),
        ("cache_dir", config.cache_dir),
    ]

    rows = [{"setting": name, "value": value} for name, value in values]
    columns = ["setting", "value"]
    payload = {
        "command": "config show",
        "results": {name: value for name, value in values},
    }

    fmt = _format_of(args)
    if fmt == "table":
        print(render_table(rows, columns, "Configuration"))
        return 0
    print(render_result(rows, columns, payload, fmt))
    return 0


def _cmd_config_set(args: argparse.Namespace) -> int:
    """Run the config set command.

    The file that is written can always be read again, and a file that
    cannot be parsed is never overwritten.
    """
    provider = args.provider
    key = str(args.key).strip().lower()
    if key not in CONFIG_KEYS[provider]:
        raise UsageError(
            "unknown key {0} for {1}. Use one of {2}.".format(
                key, provider, ", ".join(CONFIG_KEYS[provider])
            )
        )

    value = args.value
    if value is None:
        value = _read_secret()

    path = _config_path()
    try:
        data = read_config_file(path)
    except ConfigFileError as exc:
        print(
            "Error: the config file {0} cannot be parsed, so it was not changed. ({1})".format(
                path, exc
            ),
            file=sys.stderr,
        )
        return 2

    section = data.get(provider)
    if section is None:
        section = {}
        data[provider] = section
    if not isinstance(section, dict):
        print(
            "Error: the section [{0}] in {1} is not a table, so it was not changed.".format(
                provider, path
            ),
            file=sys.stderr,
        )
        return 2
    section[key] = value

    try:
        _write_config_data(path, data)
    except OSError as exc:
        print(
            "Error: the config file {0} cannot be written. ({1})".format(path, exc),
            file=sys.stderr,
        )
        return 2

    print("Wrote {0}.{1} to {2}.".format(provider, key, path))
    return 0


def _read_secret() -> str:
    """Read a value from the terminal without showing it."""
    try:
        import getpass

        return getpass.getpass("value: ")
    except Exception:  # noqa: BLE001 - the terminal may not allow it
        return sys.stdin.readline().strip()


def _cmd_config_init(args: argparse.Namespace) -> int:
    """Run the config init command."""
    path = _config_path()
    if os.path.exists(path):
        print("{0} already exists. Nothing was changed.".format(path))
        return 0

    try:
        _write_config_data(path, dict(CONFIG_SETTINGS))
    except OSError as exc:
        print(
            "Error: the config file {0} cannot be written. ({1})".format(path, exc),
            file=sys.stderr,
        )
        return 2
    print("Created {0}. Put your keys in it, or use the environment.".format(path))
    return 0


# ----------------------------------------------------------------------
# The entry point
# ----------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    """Run the tool. Return the exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    command = getattr(args, "command", None)
    if not command:
        parser.print_help()
        return 2

    try:
        # The format is checked before the work starts, so a command that
        # asks for two formats never calls a provider.
        _format_of(args)
        return _run(args, command)
    except UsageError as exc:
        print("Error: {0}".format(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("", file=sys.stderr)
        return 130


def _run(args: argparse.Namespace, command: str) -> int:
    """Run the command that the user asked for."""
    if command == "search":
        return _cmd_search(args)
    if command == "geocode":
        return _cmd_geocode(args)
    if command == "reverse":
        return _cmd_reverse(args)
    if command == "route":
        return _cmd_route(args)
    if command == "matrix":
        return _cmd_matrix(args)
    if command == "compare":
        return _cmd_compare(args)
    if command == "convert":
        return _cmd_convert(args)
    if command == "district":
        return _cmd_district(args)
    if command == "weather":
        return _cmd_weather(args)
    if command == "providers":
        return _cmd_providers(args)
    if command == "config":
        return _cmd_config(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
