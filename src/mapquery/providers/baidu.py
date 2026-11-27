"""The Baidu Maps provider.

Two channels:

- direct: the official WebService API, called with the AK that Baidu ships
  in its own page bundle. It needs no key of the user. The web route of
  map.baidu.com is the fallback when the official API fails.
- official: the documented WebService API. It uses the key in BAIDU_MAP_AK.

The direct channel cannot do a nearby search and it cannot do a route,
because the routing service is switched off on the shared AK.

Baidu works in BD-09. The web route does not return a plain latitude and
longitude for a POI. It returns BD09MC, Baidu Mercator metres, so the
Mercator conversion is done here.

Every coordinate that leaves this module is GCJ-02 in (lng, lat) order.
"""

from typing import Any, Dict, List, Optional, Set, Tuple

from ..coords import bd09_to_gcj02, gcj02_to_bd09
from ..http import is_rate_limited
from ..mercator import mc_to_ll
from ..models import Channel, Coord, GeoResult, Place, ProviderError, ProviderStatus, Route
from .base import ALL_CHINA, Provider
from .direct_keys import BAIDU_FRONTEND_AK

# The base address of both channels. The direct channel uses a path such
# as place/v2/search and the web route uses the root.
BASE = "https://api.map.baidu.com/"

# The site the direct channel pretends to come from.
REFERER = "https://map.baidu.com/"

# The features of the direct channel. The nearby search needs a route that
# the web route does not have, and the routing service is switched off on
# the shared AK.
DIRECT_FEATURES = frozenset({"search", "geocode", "reverse"})

# The features of the official channel.
OFFICIAL_FEATURES = frozenset({"search", "geocode", "reverse", "route"})

# The largest page size of the official search API.
MAX_PAGE_SIZE = 20


class BaiduProvider(Provider):
    """Baidu Maps, in BD-09 and Baidu Mercator."""

    name = "baidu"
    display_name = "Baidu Maps"
    key_env_var = "BAIDU_MAP_AK"

    def channels(self) -> List[Channel]:
        """Return the channels this provider can use."""
        return [Channel.DIRECT, Channel.OFFICIAL]

    def features_for(self, channel: Channel) -> Set[str]:
        """Return the features this provider can do on one channel."""
        if channel == Channel.OFFICIAL:
            return set(OFFICIAL_FEATURES)
        return set(DIRECT_FEATURES)

    def modes_for(self, channel: Channel) -> Set[str]:
        """Return the route modes this provider can do on one channel.

        Baidu has a driving route on the official API. The other modes
        are not part of the tool, so they are not offered.
        """
        if channel == Channel.OFFICIAL:
            return {"driving"}
        return set()

    def limits_for(self, channel: Channel) -> List[str]:
        """Return the limits of Baidu on one channel.

        The nearby search needs the official channel, because the web
        route of Baidu has no route for it.
        """
        if channel == Channel.DIRECT:
            return ["a nearby search needs the official channel"]
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
        if self.active_channel() == Channel.OFFICIAL:
            return self._search_official(keyword, city, near, radius, limit)
        if near is not None:
            # The nearby search cannot be done on the direct channel. The
            # web route of Baidu has no route for it. The official channel
            # can do it, with the key of the user, so the status says
            # that one key would open it.
            raise self.limit_error(
                "search with a near filter", other_channel_can=True
            )
        return self._search_direct(keyword, city, limit)

    def _search_direct(self, keyword: str, city: Optional[str], limit: int) -> List[Place]:
        """Search with the official API and the AK of the front-end bundle.

        The web route of Baidu is the fallback. It is used when the
        official API does not answer with data.
        """
        try:
            return self._search_api(keyword, city, None, None, limit, self._ak())
        except ProviderError:
            return self._search_web(keyword, city, limit)

    def _search_web(self, keyword: str, city: Optional[str], limit: int) -> List[Place]:
        """Search with the web route of map.baidu.com."""
        params = {
            "qt": "s",
            "wd": keyword,
            "c": city or "1",
            "pn": "0",
            "rn": str(max(1, min(int(limit), 50))),
            "ie": "utf-8",
            "oue": "1",
            "from": "webmap",
        }
        body = self.http.get_json(
            BASE,
            params=params,
            referer=REFERER,
            provider=self.name,
        )
        return self.parse_search_places(body)

    def _search_official(
        self,
        keyword: str,
        city: Optional[str],
        near: Optional[Coord],
        radius: Optional[float],
        limit: int,
    ) -> List[Place]:
        """Search with the documented WebService API and the key of the user."""
        return self._search_api(keyword, city, near, radius, limit, self._ak())

    def _search_api(
        self,
        keyword: str,
        city: Optional[str],
        near: Optional[Coord],
        radius: Optional[float],
        limit: int,
        ak: str,
    ) -> List[Place]:
        """Search with the place/v2/search route of the WebService API.

        The city must be a region name, such as Beijing. When no city is
        given the whole country is searched. The page number starts at 0.
        """
        params: Dict[str, Any] = {
            "query": keyword,
            "region": city or ALL_CHINA,
            "scope": "2",
            "output": "json",
            "page_size": str(max(1, min(int(limit), MAX_PAGE_SIZE))),
            "page_num": "0",
            "ak": ak,
        }
        if near is not None:
            bd_lng, bd_lat = gcj02_to_bd09(near[0], near[1])
            params["location"] = "{0},{1}".format(bd_lat, bd_lng)
            params["radius"] = str(int(radius if radius else 1000))
        body = self.http.get_json(
            BASE + "place/v2/search",
            params=params,
            referer=REFERER,
            provider=self.name,
        )
        self._check_official(body)
        return self.parse_official_search(body)

    def parse_search_places(self, body: Any) -> List[Place]:
        """Turn a qt=s reply into a list of places."""
        self._check_rate_limit(body)
        if not isinstance(body, dict):
            return []
        content = body.get("content")
        if not isinstance(content, list):
            return []
        places: List[Place] = []
        for entry in content:
            if not isinstance(entry, dict):
                continue
            place = self._place_from_entry(entry)
            if place is not None:
                places.append(place)
        return places

    def _place_from_entry(self, entry: Dict[str, Any]) -> Optional[Place]:
        """Turn one POI record into a place. Return None when it has no position."""
        mercator = self._mercator_of(entry)
        if mercator is None:
            return None
        bd_lng, bd_lat = mc_to_ll(mercator[0], mercator[1])
        lng, lat = bd09_to_gcj02(bd_lng, bd_lat)

        name = self._text(entry.get("name"))
        address = self._text(entry.get("addr"))
        if not address:
            address = self._text(entry.get("area_name"))

        category = self._text(entry.get("std_tag")) or self._text(entry.get("di_tag"))

        return Place(
            name=name,
            address=address,
            lng=lng,
            lat=lat,
            provider=self.name,
            category=category or None,
            uid=self._text(entry.get("uid")) or None,
            raw=entry,
        )

    def _mercator_of(self, entry: Dict[str, Any]) -> Optional[Tuple[float, float]]:
        """Return the Baidu Mercator metres of one POI record.

        The best value comes first:

        1. ext.detail_info.navi_xy.diPoint
        2. ext.detail_info.point
        3. the top level x and y, which are the same value times 100
        """
        detail = self._dict(entry.get("ext")).get("detail_info")
        detail = self._dict(detail)

        navi = self._dict(detail.get("navi_xy"))
        di_point = self._dict(navi.get("diPoint"))
        if di_point.get("x") is not None and di_point.get("y") is not None:
            return (self._as_float(di_point.get("x")), self._as_float(di_point.get("y")))

        point = self._dict(detail.get("point"))
        if point.get("x") is not None and point.get("y") is not None:
            return (self._as_float(point.get("x")), self._as_float(point.get("y")))

        if entry.get("x") is not None and entry.get("y") is not None:
            return (
                self._as_float(entry.get("x")) / 100.0,
                self._as_float(entry.get("y")) / 100.0,
            )

        return None

    def parse_official_search(self, body: Any) -> List[Place]:
        """Turn a place/v2/search reply into a list of places.

        The reply holds the POI list under "results" and the number of
        hits under "total". The position of every POI is BD-09 in lat,lng
        order.
        """
        if not isinstance(body, dict):
            return []
        items = body.get("results")
        if not isinstance(items, list):
            items = self._dict(body.get("result")).get("items")
        if not isinstance(items, list):
            return []
        places: List[Place] = []
        for entry in items:
            if not isinstance(entry, dict):
                continue
            location = self._dict(entry.get("location"))
            if location.get("lng") is None or location.get("lat") is None:
                continue
            lng, lat = bd09_to_gcj02(
                self._as_float(location.get("lng")), self._as_float(location.get("lat"))
            )
            detail = self._dict(entry.get("detail_info"))
            places.append(
                Place(
                    name=self._text(entry.get("name")),
                    address=self._text(entry.get("address")),
                    lng=lng,
                    lat=lat,
                    provider=self.name,
                    category=self._text(detail.get("tag")) or None,
                    uid=self._text(entry.get("uid")) or None,
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
            return self._geocode_api(address, city, self._ak())
        return self._geocode_direct(address, city)

    def _geocode_direct(self, address: str, city: Optional[str]) -> GeoResult:
        """Geocode with the official API and the AK of the front-end bundle.

        The web route of Baidu is the fallback. It is used when the
        official API does not answer with data.
        """
        try:
            return self._geocode_api(address, city, self._ak())
        except ProviderError:
            return self._geocode_web(address, city)

    def _geocode_web(self, address: str, city: Optional[str]) -> GeoResult:
        """Geocode with the web route of map.baidu.com."""
        params = {
            "qt": "gc",
            "wd": address,
            "c": city or "1",
            "ie": "utf-8",
            "oue": "1",
            "from": "webmap",
        }
        body = self.http.get_json(
            BASE,
            params=params,
            referer=REFERER,
            provider=self.name,
        )
        return self.parse_geocode(body)

    def _geocode_api(self, address: str, city: Optional[str], ak: str) -> GeoResult:
        """Geocode with the geocoding/v3 route of the WebService API."""
        params = {
            "address": address,
            "city": city or ALL_CHINA,
            "output": "json",
            "ak": ak,
        }
        body = self.http.get_json(
            BASE + "geocoding/v3/",
            params=params,
            referer=REFERER,
            provider=self.name,
        )
        self._check_official(body)
        return self.parse_official_geocode(body)

    def parse_geocode(self, body: Any) -> GeoResult:
        """Turn a qt=gc reply into a geo result."""
        self._check_rate_limit(body)
        if not isinstance(body, dict):
            raise ProviderError(
                "Baidu sent no data for the address", ProviderStatus.ERROR
            )
        content = self._dict(body.get("content"))
        coord = self._dict(content.get("coord"))
        if coord.get("x") is None or coord.get("y") is None:
            raise ProviderError(
                "Baidu found no place for the address", ProviderStatus.ERROR
            )
        bd_lng, bd_lat = mc_to_ll(self._as_float(coord.get("x")), self._as_float(coord.get("y")))
        lng, lat = bd09_to_gcj02(bd_lng, bd_lat)

        result = self._dict(body.get("result"))
        name = self._text(content.get("wd")) or self._text(result.get("wd"))

        return GeoResult(
            provider=self.name,
            address=name,
            lng=lng,
            lat=lat,
            level=self._text(content.get("catalog")) or None,
            raw=body,
        )

    def parse_official_geocode(self, body: Any) -> GeoResult:
        """Turn a geocoding/v3 reply into a geo result."""
        if not isinstance(body, dict):
            raise ProviderError("Baidu sent no data", ProviderStatus.ERROR)
        result = self._dict(body.get("result"))
        location = self._dict(result.get("location"))
        if location.get("lng") is None or location.get("lat") is None:
            raise ProviderError(
                "Baidu found no place for the address", ProviderStatus.ERROR
            )
        lng, lat = bd09_to_gcj02(
            self._as_float(location.get("lng")), self._as_float(location.get("lat"))
        )
        component = self._dict(result.get("addressComponent"))
        address = self._text(result.get("formatted_address"))
        if not address:
            address = self._text(component.get("city")) + self._text(component.get("district"))

        return GeoResult(
            provider=self.name,
            address=address,
            lng=lng,
            lat=lat,
            level=self._text(result.get("level")) or None,
            raw=body,
        )

    # ------------------------------------------------------------------
    # Reverse geocode
    # ------------------------------------------------------------------

    def reverse_geocode(self, lng: float, lat: float) -> GeoResult:
        """Turn GCJ-02 coordinates into an address."""
        if self.active_channel() == Channel.OFFICIAL:
            return self._reverse_api(lng, lat, self._ak())
        return self._reverse_direct(lng, lat)

    def _reverse_direct(self, lng: float, lat: float) -> GeoResult:
        """Reverse geocode with the official API and the front-end AK.

        The web route of Baidu is the fallback. It is used when the
        official API does not answer with data.
        """
        try:
            return self._reverse_api(lng, lat, self._ak())
        except ProviderError:
            return self._reverse_web(lng, lat)

    def _reverse_web(self, lng: float, lat: float) -> GeoResult:
        """Reverse geocode with the web route of map.baidu.com.

        The location of this route is in BD-09 and the order is lat,lng.
        """
        bd_lng, bd_lat = gcj02_to_bd09(lng, lat)
        params = {
            "qt": "rgc",
            "location": "{0},{1}".format(bd_lat, bd_lng),
            "c": "1",
            "ie": "utf-8",
            "oue": "1",
            "from": "webmap",
        }
        body = self.http.get_json(
            BASE,
            params=params,
            referer=REFERER,
            provider=self.name,
        )
        return self.parse_reverse(body)

    def _reverse_api(self, lng: float, lat: float, ak: str) -> GeoResult:
        """Reverse geocode with the reverse_geocoding/v3 route.

        The location of this route is in BD-09 and the order is lat,lng.
        """
        bd_lng, bd_lat = gcj02_to_bd09(lng, lat)
        params = {
            "location": "{0},{1}".format(bd_lat, bd_lng),
            "output": "json",
            "ak": ak,
        }
        body = self.http.get_json(
            BASE + "reverse_geocoding/v3/",
            params=params,
            referer=REFERER,
            provider=self.name,
        )
        self._check_official(body)
        return self.parse_official_reverse(body)

    def parse_reverse(self, body: Any) -> GeoResult:
        """Turn a qt=rgc reply into a geo result."""
        self._check_rate_limit(body)
        if not isinstance(body, dict):
            raise ProviderError("Baidu sent no data", ProviderStatus.ERROR)
        result = self._dict(body.get("result"))
        location = self._dict(result.get("location"))
        if location.get("lng") is None or location.get("lat") is None:
            raise ProviderError(
                "Baidu found no address for the point", ProviderStatus.ERROR
            )
        lng, lat = bd09_to_gcj02(
            self._as_float(location.get("lng")), self._as_float(location.get("lat"))
        )

        component = self._dict(result.get("addressComponent"))
        address = self._text(result.get("formatted_address"))
        if not address:
            address = self._text(result.get("sematic_description"))
        if not address:
            address = self._text(result.get("semantic_description"))
        if not address:
            parts = [
                self._text(component.get("province")),
                self._text(component.get("city")),
                self._text(component.get("district")),
            ]
            address = "".join([part for part in parts if part])

        return GeoResult(
            provider=self.name,
            address=address,
            lng=lng,
            lat=lat,
            raw=body,
        )

    def parse_official_reverse(self, body: Any) -> GeoResult:
        """Turn a reverse_geocoding/v3 reply into a geo result."""
        if not isinstance(body, dict):
            raise ProviderError("Baidu sent no data", ProviderStatus.ERROR)
        result = self._dict(body.get("result"))
        location = self._dict(result.get("location"))
        if location.get("lng") is None or location.get("lat") is None:
            raise ProviderError(
                "Baidu found no address for the point", ProviderStatus.ERROR
            )
        lng, lat = bd09_to_gcj02(
            self._as_float(location.get("lng")), self._as_float(location.get("lat"))
        )

        component = self._dict(result.get("addressComponent"))
        address = self._text(result.get("formatted_address"))
        if not address:
            parts = [
                self._text(component.get("province")),
                self._text(component.get("city")),
                self._text(component.get("district")),
                self._text(component.get("street")),
            ]
            address = "".join([part for part in parts if part])

        return GeoResult(
            provider=self.name,
            address=address,
            lng=lng,
            lat=lat,
            level=self._text(component.get("district")) or None,
            raw=body,
        )

    # ------------------------------------------------------------------
    # Place detail
    # ------------------------------------------------------------------

    def place_detail(self, uid: str) -> Dict[str, Any]:
        """Return the full detail of one place, found by its uid.

        Both channels use the place/v2/detail route. The direct channel
        uses the AK of the front-end bundle.
        """
        params = {
            "uid": uid,
            "scope": "2",
            "output": "json",
            "ak": self._ak(),
        }
        body = self.http.get_json(
            BASE + "place/v2/detail",
            params=params,
            referer=REFERER,
            provider=self.name,
        )
        self._check_official(body)
        return self._dict(body.get("result"))

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

        Baidu needs no city for a route, so the city is ignored.
        """
        if self.active_channel() == Channel.OFFICIAL:
            return self._route_official(origin, destination, mode)
        raise self.not_supported("route")

    def _route_official(
        self,
        origin: Coord,
        destination: Coord,
        mode: str,
    ) -> Route:
        """Find a route with the documented WebService API."""
        if mode != "driving":
            raise self.mode_error(mode)
        bd_origin = gcj02_to_bd09(origin[0], origin[1])
        bd_destination = gcj02_to_bd09(destination[0], destination[1])
        params = {
            "origin": "{0},{1}".format(bd_origin[1], bd_origin[0]),
            "destination": "{0},{1}".format(bd_destination[1], bd_destination[0]),
            "output": "json",
            "ak": self._ak(),
        }
        body = self.http.get_json(
            BASE + "direction/v2/driving",
            params=params,
            provider=self.name,
        )
        self._check_official(body)
        return self.parse_official_route(body, origin, destination, mode)

    def parse_official_route(
        self,
        body: Any,
        origin: Coord,
        destination: Coord,
        mode: str = "driving",
    ) -> Route:
        """Turn a direction/v2/driving reply into a route."""
        if not isinstance(body, dict):
            raise ProviderError("Baidu sent no data", ProviderStatus.ERROR)
        result = self._dict(body.get("result"))
        routes = result.get("routes")
        if not isinstance(routes, list) or not routes:
            raise ProviderError("Baidu found no route", ProviderStatus.ERROR)
        first = self._dict(routes[0])

        steps: List[Dict[str, Any]] = []
        raw_steps = first.get("steps")
        if isinstance(raw_steps, list):
            for raw_step in raw_steps:
                step = self._dict(raw_step)
                points: List[Coord] = []
                polyline = step.get("polyline")
                if isinstance(polyline, list):
                    for point in polyline:
                        point = self._dict(point)
                        values = point.get("polyline")
                        if isinstance(values, list) and len(values) >= 2:
                            lng, lat = bd09_to_gcj02(
                                self._as_float(values[0]), self._as_float(values[1])
                            )
                            points.append((lng, lat))
                steps.append(
                    {
                        "instruction": self._text(step.get("instruction")),
                        "road": self._text(step.get("road")),
                        "distance_m": self._as_float(step.get("distance")),
                        "duration_s": self._as_float(step.get("duration")),
                        "polyline": points,
                    }
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
    # Small helpers
    # ------------------------------------------------------------------

    def _ak(self) -> str:
        """Return the AK to use.

        The official channel uses the key of the user. The direct channel
        uses the AK that Baidu ships in its own page bundle.
        """
        if self.active_channel() == Channel.OFFICIAL:
            return self.config.baidu_ak
        return BAIDU_FRONTEND_AK

    def _check_official(self, body: Any) -> None:
        """Raise an error when the official API did not answer with data."""
        self._check_rate_limit(body)
        if not isinstance(body, dict):
            raise ProviderError("Baidu sent no data", ProviderStatus.ERROR)
        status = body.get("status")
        if status is not None and int(status) != 0:
            # The message of the provider can be in Chinese. The interface
            # is English only, so the message stays in the raw reply.
            raise ProviderError(
                "Baidu answered with an error", ProviderStatus.ERROR, raw=body
            )

    def _check_rate_limit(self, body: Any) -> None:
        """Raise a rate limit error when the body says the rate is too high."""
        if is_rate_limited(body):
            raise ProviderError(
                "Baidu answered: the rate limit was hit",
                ProviderStatus.RATE_LIMITED,
            )
