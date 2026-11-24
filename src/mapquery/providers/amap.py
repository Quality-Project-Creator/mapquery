"""The Amap (Gaode) provider.

Two channels:

- direct: the front-end route of www.amap.com. It needs no key.
- official: the documented WebService API. It uses the key in AMAP_API_KEY.

Amap works in GCJ-02 and its order is lng,lat, which is the order that the
tool keeps. Every coordinate that leaves this module is GCJ-02 in
(lng, lat) order.
"""

from typing import Any, Dict, List, Optional, Set

from ..http import is_rate_limited
from ..models import Channel, Coord, GeoResult, Place, ProviderError, ProviderStatus, Route
from .base import ALL_CHINA, Provider
from .direct_keys import AMAP_FRONTEND_KEY

# The base address of the direct channel.
DIRECT_BASE = "https://www.amap.com/_AMapService/v3/"

# The base address of the official channel.
OFFICIAL_BASE = "https://restapi.amap.com/v3/"

# The base address of the official v4 route. The cycling route of Amap is
# only there, the v3 route does not know it.
OFFICIAL_V4_BASE = "https://restapi.amap.com/v4/"

# The site the direct channel pretends to come from.
REFERER = "https://www.amap.com/"

# The features of the direct channel. The POI search answers with HTTP 403
# and the reverse geocode answers with a risk control body, so neither of
# them works on this channel.
DIRECT_FEATURES = frozenset({"geocode", "route"})

# The features of the official channel.
OFFICIAL_FEATURES = frozenset(
    {"search", "geocode", "reverse", "route", "district", "weather"}
)

# The route modes of the direct channel. Only driving was traced.
DIRECT_MODES = frozenset({"driving"})

# The route modes of the official channel. The name of the cycling mode is
# the one of the provider, "bicycling".
OFFICIAL_MODES = frozenset({"driving", "walking", "bicycling", "transit"})


class AmapProvider(Provider):
    """Amap (Gaode), in GCJ-02."""

    name = "amap"
    display_name = "Amap (Gaode)"
    key_env_var = "AMAP_API_KEY"

    # The features that the direct channel cannot do. They all work on
    # the official channel, so they need the key of the user.
    key_features = frozenset({"search", "reverse", "district", "weather"})

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
        if channel == Channel.OFFICIAL:
            return set(OFFICIAL_MODES)
        return set(DIRECT_MODES)

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
        if self.active_channel() != Channel.OFFICIAL:
            raise self.not_supported("search")

        params: Dict[str, Any] = {
            "keywords": keyword,
            "city": city or ALL_CHINA,
            "offset": str(max(1, min(int(limit), 25))),
            "page": "1",
            "key": self.config.amap_key,
            "output": "json",
        }
        if near is not None:
            params = {
                "location": "{0},{1}".format(near[0], near[1]),
                "keywords": keyword,
                "radius": str(int(radius if radius else 1000)),
                "offset": str(max(1, min(int(limit), 25))),
                "page": "1",
                "key": self.config.amap_key,
                "output": "json",
            }
            path = "place/around"
        else:
            path = "place/text"

        body = self.http.get_json(
            OFFICIAL_BASE + path,
            params=params,
            provider=self.name,
        )
        return self.parse_search(body)

    def parse_search(self, body: Any) -> List[Place]:
        """Turn a place/text or place/around reply into a list of places."""
        self._check_status(body)
        if not isinstance(body, dict):
            return []
        pois = body.get("pois")
        if not isinstance(pois, list):
            return []
        places: List[Place] = []
        for entry in pois:
            if not isinstance(entry, dict):
                continue
            location = self._split_location(entry.get("location"))
            if location is None:
                continue
            places.append(
                Place(
                    name=self._text(entry.get("name")),
                    address=self._text(entry.get("address")),
                    lng=location[0],
                    lat=location[1],
                    provider=self.name,
                    category=self._text(entry.get("type")) or None,
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
        if self.active_channel() == Channel.OFFICIAL:
            params = {
                "address": address,
                "city": city or ALL_CHINA,
                "key": self.config.amap_key,
                "output": "json",
            }
            body = self.http.get_json(
                OFFICIAL_BASE + "geocode/geo",
                params=params,
                provider=self.name,
            )
            return self.parse_geocode(body)

        params = self._direct_params({"address": address, "city": city or ALL_CHINA})
        body = self.http.get_json(
            DIRECT_BASE + "geocode/geo",
            params=params,
            referer=REFERER,
            provider=self.name,
            headers={"Origin": REFERER},
        )
        return self.parse_geocode(body)

    def parse_geocode(self, body: Any) -> GeoResult:
        """Turn a geocode/geo reply into a geo result."""
        self._check_status(body)
        if not isinstance(body, dict):
            raise ProviderError("Amap sent no data", ProviderStatus.ERROR)
        geocodes = body.get("geocodes")
        if not isinstance(geocodes, list) or not geocodes:
            raise ProviderError(
                "Amap found no place for the address", ProviderStatus.ERROR
            )
        first = self._dict(geocodes[0])
        location = self._split_location(first.get("location"))
        if location is None:
            raise ProviderError(
                "Amap found no place for the address", ProviderStatus.ERROR
            )
        return GeoResult(
            provider=self.name,
            address=self._text(first.get("formatted_address")),
            lng=location[0],
            lat=location[1],
            level=self._text(first.get("level")) or None,
            raw=body,
        )

    # ------------------------------------------------------------------
    # Reverse geocode
    # ------------------------------------------------------------------

    def reverse_geocode(self, lng: float, lat: float) -> GeoResult:
        """Turn GCJ-02 coordinates into an address."""
        if self.active_channel() != Channel.OFFICIAL:
            raise self.not_supported("reverse")
        params = {
            "location": "{0},{1}".format(lng, lat),
            "key": self.config.amap_key,
            "output": "json",
        }
        body = self.http.get_json(
            OFFICIAL_BASE + "geocode/regeo",
            params=params,
            provider=self.name,
        )
        return self.parse_reverse(body)

    def parse_reverse(self, body: Any) -> GeoResult:
        """Turn a geocode/regeo reply into a geo result."""
        self._check_status(body)
        if not isinstance(body, dict):
            raise ProviderError("Amap sent no data", ProviderStatus.ERROR)
        regeocode = self._dict(body.get("regeocode"))
        location = self._split_location(regeocode.get("location"))
        if location is None:
            raise ProviderError(
                "Amap found no address for the point", ProviderStatus.ERROR
            )
        return GeoResult(
            provider=self.name,
            address=self._text(regeocode.get("formatted_address")),
            lng=location[0],
            lat=location[1],
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
    ) -> Route:
        """Find a route between two GCJ-02 points."""
        channel = self.active_channel()
        if mode not in self.modes_for(channel):
            raise self.mode_error(mode)

        if channel == Channel.OFFICIAL:
            params = {
                "origin": "{0},{1}".format(origin[0], origin[1]),
                "destination": "{0},{1}".format(destination[0], destination[1]),
                "key": self.config.amap_key,
                "output": "json",
            }
            body = self.http.get_json(
                self._official_route_url(mode),
                params=params,
                provider=self.name,
            )
            return self.parse_route(body, origin, destination, mode)

        params = self._direct_params(
            {
                "origin": "{0},{1}".format(origin[0], origin[1]),
                "destination": "{0},{1}".format(destination[0], destination[1]),
            }
        )
        body = self.http.get_json(
            DIRECT_BASE + "direction/driving",
            params=params,
            referer=REFERER,
            provider=self.name,
            headers={"Origin": REFERER},
        )
        return self.parse_route(body, origin, destination, mode)

    def parse_route(
        self,
        body: Any,
        origin: Coord,
        destination: Coord,
        mode: str = "driving",
    ) -> Route:
        """Turn a route reply into a route.

        The v3 route holds its paths under route.paths. The v4 route,
        which is the one that knows the cycling mode, holds them under
        data.paths. Both shapes are read here, and both give the same
        steps.
        """
        self._check_status(body)
        if not isinstance(body, dict):
            raise ProviderError("Amap sent no data", ProviderStatus.ERROR)
        paths = self._route_paths(body)
        if not paths:
            raise ProviderError("Amap found no route", ProviderStatus.ERROR)
        first = self._dict(paths[0])

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
                        self._parse_polyline(step.get("polyline")),
                        step.get("action"),
                    )
                )

        return Route(
            provider=self.name,
            mode=mode,
            distance_m=self._as_float(first.get("distance")),
            duration_s=self._as_float(first.get("duration")),
            origin=origin,
            destination=destination,
            steps=steps,
            raw=body,
        )

    # ------------------------------------------------------------------
    # District and weather
    # ------------------------------------------------------------------

    def district(self, keyword: str) -> List[Dict[str, Any]]:
        """Return the administrative districts of a keyword."""
        if self.active_channel() != Channel.OFFICIAL:
            raise self.not_supported("district")
        params = {
            "keywords": keyword,
            "subdistrict": "1",
            "key": self.config.amap_key,
            "output": "json",
        }
        body = self.http.get_json(
            OFFICIAL_BASE + "config/district",
            params=params,
            provider=self.name,
        )
        self._check_status(body)
        districts = body.get("districts")
        if not isinstance(districts, list):
            return []
        return [item for item in districts if isinstance(item, dict)]

    def weather(self, adcode: str) -> Dict[str, Any]:
        """Return the weather of an area code."""
        if self.active_channel() != Channel.OFFICIAL:
            raise self.not_supported("weather")
        params = {
            "city": adcode,
            "extensions": "all",
            "key": self.config.amap_key,
            "output": "json",
        }
        body = self.http.get_json(
            OFFICIAL_BASE + "weather/weatherInfo",
            params=params,
            provider=self.name,
        )
        self._check_status(body)
        return body

    # ------------------------------------------------------------------
    # Small helpers
    # ------------------------------------------------------------------

    def _direct_params(self, extra: Dict[str, Any]) -> Dict[str, Any]:
        """Return the query string of the direct channel."""
        params: Dict[str, Any] = {
            "key": AMAP_FRONTEND_KEY,
            "platform": "JS",
            "s": "rsv3",
            "logversion": "2.0",
            "sdkversion": "2.0",
            "cetype": "unify",
        }
        params.update(extra)
        return params

    @staticmethod
    def _official_route_path(mode: str) -> str:
        """Return the path of one route mode of the official channel."""
        paths = {
            "driving": "direction/driving",
            "walking": "direction/walking",
            "bicycling": "direction/bicycling",
            "transit": "direction/transit/integrated",
        }
        return paths.get(mode, "direction/driving")

    @classmethod
    def _official_route_url(cls, mode: str) -> str:
        """Return the address of one route mode of the official channel.

        The cycling route of Amap is on the v4 route only. The v3 route
        does not know it.
        """
        if mode == "bicycling":
            return OFFICIAL_V4_BASE + cls._official_route_path(mode)
        return OFFICIAL_BASE + cls._official_route_path(mode)

    @staticmethod
    def _route_paths(body: Dict[str, Any]) -> List[Any]:
        """Return the paths of a route reply.

        The v3 route holds them under route.paths. The v4 route holds
        them under data.paths. The v4 route is the one that knows the
        cycling mode, so both places are read here.
        """
        for holder in ("route", "data"):
            section = body.get(holder)
            if not isinstance(section, dict):
                continue
            paths = section.get("paths")
            if isinstance(paths, list):
                return paths
        return []

    def _check_status(self, body: Any) -> None:
        """Raise an error when Amap did not answer with data.

        The v3 API of Amap uses status "1" for a good answer and status
        "0" for a failed one. The v4 API uses errcode 0 for a good answer
        and a non zero errcode for a failed one. A rate limit is reported
        with the rate limit status.
        """
        if is_rate_limited(body):
            raise ProviderError(
                "Amap answered: the rate limit was hit",
                ProviderStatus.RATE_LIMITED,
            )
        if not isinstance(body, dict):
            raise ProviderError("Amap sent no data", ProviderStatus.ERROR)

        errcode = body.get("errcode")
        if errcode is not None:
            # This is the v4 shape. A non zero errcode is a failure.
            if self._as_float(errcode, -1.0) != 0.0:
                # The message of the provider can be in Chinese. The
                # interface is English only, so the message stays in the
                # raw reply.
                raise ProviderError(
                    "Amap answered with an error", ProviderStatus.ERROR, raw=body
                )
            return

        status = self._text(body.get("status"))
        if status and status != "1":
            # The message of the provider can be in Chinese. The interface
            # is English only, so the message stays in the raw reply.
            raise ProviderError(
                "Amap answered with an error", ProviderStatus.ERROR, raw=body
            )

    def _split_location(self, value: Any) -> Optional[Coord]:
        """Return a "lng,lat" string as a pair of floats.

        Return None when the text cannot be read.
        """
        if not isinstance(value, str) or "," not in value:
            return None
        parts = value.split(",")
        if len(parts) < 2:
            return None
        try:
            return (float(parts[0]), float(parts[1]))
        except ValueError:
            return None
