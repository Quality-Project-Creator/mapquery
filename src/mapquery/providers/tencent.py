"""The Tencent Maps provider.

Two channels:

- direct: the front-end route of map.qq.com. It needs no key.
- official: the documented WebService API. It uses the key in TENCENT_MAP_KEY.

Both channels use the same address, https://apis.map.qq.com/ws/. The
official channel only uses the key of the user.

Tencent works in GCJ-02 and its order is lat,lng. Every coordinate that
leaves this module is GCJ-02 in (lng, lat) order.
"""

from typing import Any, Dict, List, Optional, Set

from ..http import is_rate_limited
from ..models import Channel, Coord, GeoResult, Place, ProviderError, ProviderStatus, Route
from .base import Provider
from .direct_keys import TENCENT_FRONTEND_KEY

# The base address of both channels.
BASE = "https://apis.map.qq.com/ws/"

# The site the direct channel pretends to come from.
REFERER = "https://map.qq.com/"

# The features of the direct channel.
DIRECT_FEATURES = frozenset({"search", "geocode", "reverse", "route", "district"})

# The features of the official channel.
OFFICIAL_FEATURES = frozenset({"search", "geocode", "reverse", "route", "district"})

# The route modes that work on both channels. The name of the cycling
# mode is the one of the provider, "bicycling".
MODES = frozenset({"driving", "walking", "bicycling", "transit"})


class TencentProvider(Provider):
    """Tencent Maps, in GCJ-02."""

    name = "tencent"
    display_name = "Tencent Maps"
    key_env_var = "TENCENT_MAP_KEY"

    def channels(self) -> List[Channel]:
        """Return the channels this provider can use."""
        return [Channel.DIRECT, Channel.OFFICIAL]

    def features_for(self, channel: Channel) -> Set[str]:
        """Return the features this provider can do on one channel."""
        if channel == Channel.OFFICIAL:
            return set(OFFICIAL_FEATURES)
        return set(DIRECT_FEATURES)

    def modes_for(self, channel: Channel) -> Set[str]:
        """Return the route modes this provider can do on one channel."""
        return set(MODES)

    def limits_for(self, channel: Channel) -> List[str]:
        """Return the limits of Tencent on one channel.

        The suggestion route of Tencent has no nearby filter, and the
        official channel uses the same route, so a nearby search is not
        possible on either of them.
        """
        return ["a nearby search is not available"]

    def key(self) -> str:
        """Return the key to use. The official channel uses the key of the user."""
        if self.active_channel() == Channel.OFFICIAL:
            return self.config.tencent_key
        return TENCENT_FRONTEND_KEY

    # ------------------------------------------------------------------
    # POI search
    # ------------------------------------------------------------------

    def search_places(
        self,
        keyword: str,
        city: Optional[str] = None,
        near: Optional[Coord] = None,
        radius: Optional[float] = None,
        limit: int = 10,
    ) -> List[Place]:
        """Search for places. Return a list of places in GCJ-02 order."""
        if near is not None:
            # The suggestion route has no near filter, and the official
            # channel uses the same route. No channel of Tencent can do
            # a nearby search.
            raise self.limit_error("search with a near filter")

        params: Dict[str, Any] = {
            "keyword": keyword,
            "key": self.key(),
        }
        if city:
            params["region"] = city
        body = self.http.get_json(
            BASE + "place/v1/suggestion",
            params=params,
            referer=REFERER,
            provider=self.name,
        )
        places = self.parse_search(body)
        return places[: max(1, int(limit))]

    def parse_search(self, body: Any) -> List[Place]:
        """Turn a place/v1/suggestion reply into a list of places."""
        self._check_status(body)
        if not isinstance(body, dict):
            return []
        rows = body.get("data")
        if not isinstance(rows, list):
            return []
        places: List[Place] = []
        for entry in rows:
            if not isinstance(entry, dict):
                continue
            location = self._dict(entry.get("location"))
            if location.get("lng") is None or location.get("lat") is None:
                continue
            places.append(
                Place(
                    name=self._text(entry.get("title")),
                    address=self._text(entry.get("address")),
                    lng=self._as_float(location.get("lng")),
                    lat=self._as_float(location.get("lat")),
                    provider=self.name,
                    category=self._text(entry.get("category")) or None,
                    uid=self._text(entry.get("id")) or None,
                    raw=entry,
                )
            )
        return places

    # ------------------------------------------------------------------
    # Geocode
    # ------------------------------------------------------------------

    def geocode(self, address: str, city: Optional[str] = None) -> GeoResult:
        """Turn an address into coordinates in GCJ-02."""
        params: Dict[str, Any] = {
            "address": address,
            "key": self.key(),
        }
        if city:
            params["region"] = city
        body = self.http.get_json(
            BASE + "geocoder/v1/",
            params=params,
            referer=REFERER,
            provider=self.name,
        )
        return self.parse_geocode(body)

    def parse_geocode(self, body: Any) -> GeoResult:
        """Turn a geocoder/v1 reply into a geo result."""
        self._check_status(body)
        if not isinstance(body, dict):
            raise ProviderError("Tencent sent no data", ProviderStatus.ERROR)
        result = self._dict(body.get("result"))
        location = self._dict(result.get("location"))
        if location.get("lng") is None or location.get("lat") is None:
            raise ProviderError(
                "Tencent found no place for the address", ProviderStatus.ERROR
            )
        address = self._text(result.get("address")) or self._text(result.get("title"))
        return GeoResult(
            provider=self.name,
            address=address,
            lng=self._as_float(location.get("lng")),
            lat=self._as_float(location.get("lat")),
            level=self._text(result.get("level")) or None,
            raw=body,
        )

    # ------------------------------------------------------------------
    # Reverse geocode
    # ------------------------------------------------------------------

    def reverse_geocode(self, lng: float, lat: float) -> GeoResult:
        """Turn GCJ-02 coordinates into an address."""
        params = {
            "location": "{0},{1}".format(lat, lng),
            "get_poi": "1",
            "key": self.key(),
        }
        body = self.http.get_json(
            BASE + "geocoder/v1/",
            params=params,
            referer=REFERER,
            provider=self.name,
        )
        return self.parse_reverse(body)

    def parse_reverse(self, body: Any) -> GeoResult:
        """Turn a geocoder/v1 reply into a geo result."""
        self._check_status(body)
        if not isinstance(body, dict):
            raise ProviderError("Tencent sent no data", ProviderStatus.ERROR)
        result = self._dict(body.get("result"))
        location = self._dict(result.get("location"))
        if location.get("lng") is None or location.get("lat") is None:
            raise ProviderError(
                "Tencent found no address for the point", ProviderStatus.ERROR
            )

        address = self._text(result.get("address"))
        if not address:
            formatted = self._dict(result.get("formatted_addresses"))
            address = self._text(formatted.get("recommend"))

        return GeoResult(
            provider=self.name,
            address=address,
            lng=self._as_float(location.get("lng")),
            lat=self._as_float(location.get("lat")),
            raw=body,
        )

    # ------------------------------------------------------------------
    # Route
    # ------------------------------------------------------------------

    def route(
        self,
        origin: Coord,
        destination: Coord,
        mode: str = "driving",
        city: Optional[str] = None,
    ) -> Route:
        """Find a route between two GCJ-02 points.

        Tencent needs no city for a route, so the city is ignored.
        """
        if mode not in self.modes_for(self.active_channel()):
            raise self.mode_error(mode)
        params = {
            "from": "{0},{1}".format(origin[1], origin[0]),
            "to": "{0},{1}".format(destination[1], destination[0]),
            "key": self.key(),
        }
        body = self.http.get_json(
            BASE + "direction/v1/" + mode,
            params=params,
            referer=REFERER,
            provider=self.name,
        )
        return self.parse_route(body, origin, destination, mode)

    def parse_route(
        self,
        body: Any,
        origin: Coord,
        destination: Coord,
        mode: str = "driving",
    ) -> Route:
        """Turn a direction/v1 reply into a route."""
        self._check_status(body)
        if not isinstance(body, dict):
            raise ProviderError("Tencent sent no data", ProviderStatus.ERROR)
        result = self._dict(body.get("result"))
        routes = result.get("routes")
        if not isinstance(routes, list) or not routes:
            raise ProviderError("Tencent found no route", ProviderStatus.ERROR)
        first = self._dict(routes[0])

        steps: List[Dict[str, Any]] = []
        raw_steps = first.get("steps")
        if isinstance(raw_steps, list):
            for raw_step in raw_steps:
                step = self._dict(raw_step)
                steps.append(
                    self._make_step(
                        step.get("instruction"),
                        step.get("road"),
                        step.get("distance"),
                        step.get("duration"),
                        self._parse_polyline(step.get("polyline"), lat_first=True),
                    )
                )

        distance_m, duration_s = self._route_numbers(first, self.display_name)

        return Route(
            provider=self.name,
            mode=mode,
            distance_m=distance_m,
            duration_s=duration_s,
            origin=origin,
            destination=destination,
            steps=steps,
            raw=body,
        )

    # ------------------------------------------------------------------
    # District
    # ------------------------------------------------------------------

    def district(self, keyword: str) -> List[Dict[str, Any]]:
        """Return the administrative districts of a keyword."""
        params = {
            "keyword": keyword,
            "key": self.key(),
        }
        body = self.http.get_json(
            BASE + "district/v1/search",
            params=params,
            referer=REFERER,
            provider=self.name,
        )
        self._check_status(body)
        result = self._dict(body.get("result"))
        districts = result.get("district")
        if not isinstance(districts, list):
            return []
        return [item for item in districts if isinstance(item, dict)]

    # ------------------------------------------------------------------
    # Small helpers
    # ------------------------------------------------------------------

    def _check_status(self, body: Any) -> None:
        """Raise an error when Tencent did not answer with data.

        Tencent uses status 0 for a good answer. Status 120 is a rate limit
        and is reported with the rate limit status.
        """
        if is_rate_limited(body):
            raise ProviderError(
                "Tencent answered: the rate limit was hit",
                ProviderStatus.RATE_LIMITED,
            )
        if not isinstance(body, dict):
            raise ProviderError("Tencent sent no data", ProviderStatus.ERROR)
        status = body.get("status")
        if status is None:
            return
        try:
            value = int(status)
        except (TypeError, ValueError):
            return
        if value != 0:
            # The message of the provider is in Chinese. The interface is
            # English only, so the message stays in the raw reply.
            raise ProviderError(
                "Tencent answered with an error", ProviderStatus.ERROR, raw=body
            )
