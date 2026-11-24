"""A live check of the three providers.

This is a script, not a test. It calls the real endpoints once per check
and prints one status line for each of them.

The direct channel shares its keys with the live websites of the providers,
so the script sleeps between the calls. A provider that is rate limited
prints RATE_LIMITED. That is a valid answer, not a failure.

Run it from the root of the project:

    python tools/smoke.py
"""

import os
import sys
import time
from typing import Any, Callable, List, Tuple

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from mapquery.config import Config  # noqa: E402
from mapquery.http import HttpClient  # noqa: E402
from mapquery.models import ProviderError, ProviderStatus  # noqa: E402
from mapquery.providers import get_provider  # noqa: E402

# The wait time between two calls, in seconds.
SLEEP_SECONDS = 2.0

# The keyword of the search checks. It is written as an escape, so that the
# source code stays free of Chinese characters.
KEYWORD = "\u5929\u5b89\u95e8"

# The address of the geocode check.
ADDRESS = "\u5929\u5b89\u95e8\u5e7f\u573a"

# The city of the geocode check.
CITY = "\u5317\u4eac"

# The two points of the route check.
ORIGIN = (116.397428, 39.908823)
DESTINATION = (116.39667, 39.90864)


def run_check(
    label: str,
    channel: str,
    action: Callable[[], str],
) -> Tuple[str, str, str, str]:
    """Run one check and return the label, the status, the channel and the detail."""
    try:
        detail = action()
    except ProviderError as exc:
        return (label, str(exc.status), channel, exc.message)
    except Exception as exc:  # noqa: BLE001 - the script must not stop early
        return (
            label,
            str(ProviderStatus.ERROR),
            channel,
            "{0}: {1}".format(type(exc).__name__, exc),
        )
    return (label, str(ProviderStatus.OK), channel, detail)


def check_baidu_search(provider: Any) -> str:
    """Search a place with Baidu and report the first one."""
    places = provider.search_places(KEYWORD, limit=3)
    if not places:
        return "no places came back"
    first = places[0]
    return "{0} places, first {1} at {2:.6f}, {3:.6f}".format(
        len(places), first.name, first.lng, first.lat
    )


def check_amap_geocode(provider: Any) -> str:
    """Geocode an address with Amap and report the position."""
    result = provider.geocode(ADDRESS, city=CITY)
    return "{0} at {1:.6f}, {2:.6f}".format(result.address, result.lng, result.lat)


def check_amap_driving(provider: Any) -> str:
    """Ask Amap for a driving route and report the distance and the time."""
    route = provider.route(ORIGIN, DESTINATION, mode="driving")
    return "{0:.0f} m, {1:.0f} s, {2} steps".format(
        route.distance_m, route.duration_s, len(route.steps)
    )


def check_tencent_search(provider: Any) -> str:
    """Search a place with Tencent and report the first one."""
    places = provider.search_places(KEYWORD, limit=3)
    if not places:
        return "no places came back"
    first = places[0]
    return "{0} places, first {1} at {2:.6f}, {3:.6f}".format(
        len(places), first.name, first.lng, first.lat
    )


def main() -> int:
    """Run every check and print the result."""
    config = Config.load()
    http = HttpClient(config)

    checks: List[Tuple[str, str, Callable[[Any], str]]] = [
        ("baidu", "search", check_baidu_search),
        ("amap", "geocode", check_amap_geocode),
        ("amap", "driving", check_amap_driving),
        ("tencent", "search", check_tencent_search),
    ]

    results: List[Tuple[str, str, str, str]] = []
    for name, what, action in checks:
        provider = get_provider(name, config, http)
        results.append(
            run_check(
                "{0} {1}".format(name, what),
                str(provider.active_channel()),
                lambda: action(provider),
            )
        )
        time.sleep(SLEEP_SECONDS)

    print("")
    width = max(len(row[0]) for row in results)
    for label, status, channel, detail in results:
        print("{0:<{1}}  {2:<14} {3:<9} {4}".format(label, width, status, channel, detail))

    return 0


if __name__ == "__main__":
    sys.exit(main())
