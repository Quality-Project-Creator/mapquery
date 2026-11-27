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

    def limits_for(self, channel: Channel) -> List[str]:
        """Return the limits of Amap on one channel.

        The transit route of Amap needs the city of the start point, so
        the city has to be given with the route command.
        """
        if channel == Channel.OFFICIAL:
            return ["a transit route needs the city of the start point"]
        return []

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
        city: Optional[str] = None,
    ) -> Route:
        """Find a route between two GCJ-02 points.

        The transit route of Amap needs the city of the start point. The
        other routes do not need it, so they ignore it.
        """
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
            if mode == "transit":
                # The transit route of Amap needs the city of the start
                # point, and it only gives the whole plan when the
                # extension is "all".
                params["city"] = city or ALL_CHINA
                params["extensions"] = "all"
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
        data.paths. The transit route holds its plans under
        route.transits. All three shapes are read here, and all of them
        give the same steps.
        """
        self._check_status(body)
        if not isinstance(body, dict):
            raise ProviderError("Amap sent no data", ProviderStatus.ERROR)

        paths = self._route_paths(body)
        if paths:
            return self._path_route(paths[0], body, origin, destination, mode)

        transit = self._transit_route(body, origin, destination, mode)
        if transit is not None:
            return transit

        raise ProviderError("Amap found no route", ProviderStatus.ERROR)

    def _path_route(
        self,
        path: Any,
        body: Any,
        origin: Coord,
        destination: Coord,
        mode: str,
    ) -> Route:
        """Turn one path of a route reply into a route."""
        first = self._dict(path)

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

    def _transit_route(
        self,
        body: Dict[str, Any],
        origin: Coord,
        destination: Coord,
        mode: str,
    ) -> Optional[Route]:
        """Turn a transit reply into a route.

        The transit reply of Amap holds its plans under route.transits.
        A plan holds its legs under segments. A leg holds the walking
        part under walking and the bus part under bus.

        The distance of the route is the sum of the walking parts and of
        the bus lines. The time of the route is the one of the plan. When
        the reply does not hold them, None is returned, so that the
        caller says that no route was found instead of showing a number
        that is not true.
        """
        route = self._dict(body.get("route"))
        transits = route.get("transits")
        if not isinstance(transits, list) or not transits:
            return None

        plan = self._dict(transits[0])
        segments = plan.get("segments")
        if not isinstance(segments, list) or not segments:
            return None

        steps: List[Dict[str, Any]] = []
        distance = 0.0
        duration = 0.0
        have_distance = False
        have_duration = False

        for raw_segment in segments:
            segment = self._dict(raw_segment)

            walking = self._dict(segment.get("walking"))
            if walking.get("distance") is not None:
                distance += self._as_float(walking.get("distance"))
                have_distance = True
            if walking.get("duration") is not None:
                duration += self._as_float(walking.get("duration"))
                have_duration = True
            raw_steps = walking.get("steps")
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

            bus = self._dict(segment.get("bus"))
            buslines = bus.get("buslines")
            if isinstance(buslines, list):
                for raw_line in buslines:
                    line = self._dict(raw_line)
                    if line.get("distance") is not None:
                        distance += self._as_float(line.get("distance"))
                        have_distance = True
                    if line.get("duration") is not None:
                        duration += self._as_float(line.get("duration"))
                        have_duration = True
                    # A bus line has no instruction of its own. The name
                    # of the line is what the reply gives.
                    steps.append(
                        self._make_step(
                            "",
                            line.get("name"),
                            line.get("distance"),
                            line.get("duration"),
                            self._parse_polyline(line.get("polyline")),
                        )
                    )

        if not have_distance or not have_duration:
            return None

        if plan.get("duration") is not None:
            # The plan holds the time that the whole trip takes.
            duration = self._as_float(plan.get("duration"))

        return Route(
            provider=self.name,
            mode=mode,
            distance_m=distance,
            duration_s=duration,
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
