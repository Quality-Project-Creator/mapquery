"""The base class of every provider.

Every provider answers in one common shape. The tool keeps one internal
order and one internal system: the order is (lng, lat) and the system is
GCJ-02. Every provider converts at its own boundary, so the user never has
to think about coordinate systems.

A provider has one or two channels. The direct channel needs no key. The
official channel uses the key the user set in the environment. A feature the
active channel cannot do raises ProviderError with the status
NOT_SUPPORTED. The tool never invents a result.
"""

from typing import Any, Dict, List, Optional, Set

from ..config import Config
from ..http import HttpClient
from ..models import (
    Channel,
    Coord,
    GeoResult,
    Place,
    ProviderError,
    ProviderStatus,
    Route,
)

# The features a provider can offer.
FEATURES = ("search", "geocode", "reverse", "route", "district", "weather")

# The region that means the whole country. It is written as an escape, so
# that the source code stays free of Chinese characters.
ALL_CHINA = "\u5168\u56fd"


class Provider:
    """The interface that every provider follows."""

    # The short name, such as "baidu".
    name: str = ""

    # The name to show to the user, such as "Baidu Maps".
    display_name: str = ""

    # The environment variable that holds the key of this provider.
    key_env_var: str = ""

    # The features that need the key of the user on the direct channel.
    # A feature in this list is reported as not_configured when the user
    # did not set a key.
    key_features: frozenset = frozenset()

    def __init__(
        self,
        config: Config,
        http: HttpClient,
        channel: Optional[Channel] = None,
    ) -> None:
        """Store the config, the http client and the wanted channel.

        A channel of None means the provider picks the channel itself.
        """
        self.config = config
        self.http = http
        self.wanted_channel = channel

    def channels(self) -> List[Channel]:
        """Return the channels this provider can use."""
        return [Channel.DIRECT]

    def has_own_key(self) -> bool:
        """Return True when the user set a key for this provider."""
        return bool(self.config.key_for(self.name))

    def active_channel(self) -> Channel:
        """Return the channel that will be used.

        The official channel is used when the user set a key. Otherwise the
        direct channel is used.
        """
        if self.wanted_channel is not None:
            return self.wanted_channel
        if self.has_own_key() and Channel.OFFICIAL in self.channels():
            return Channel.OFFICIAL
        return Channel.DIRECT

    def features_for(self, channel: Channel) -> Set[str]:
        """Return the features this provider can do on one channel."""
        return set()

    def supports(self, feature: str) -> bool:
        """Return True when the active channel can do this feature."""
        if feature not in FEATURES:
            return False
        return feature in self.features_for(self.active_channel())

    def modes_for(self, channel: Channel) -> Set[str]:
        """Return the route modes this provider can do on one channel.

        A provider that does not name its modes does no route at all.
        """
        return set()

    def not_supported(self, feature: str) -> ProviderError:
        """Return the error for a feature the active channel cannot do."""
        return ProviderError(
            "{0} cannot do {1} on the {2} channel".format(
                self.display_name, feature, self.active_channel()
            ),
            ProviderStatus.NOT_SUPPORTED,
        )

    def mode_error(self, mode: str) -> ProviderError:
        """Return the error for a route mode the active channel cannot do.

        When the other channel can do that mode and the user has no key,
        the status is not_configured. The user then learns that one key
        would open that mode, instead of being told the provider cannot
        do it at all.
        """
        for channel in self.channels():
            if channel == self.active_channel():
                continue
            if mode in self.modes_for(channel) and not self.has_own_key():
                return ProviderError(
                    "{0} needs the key {1} for a {2} route".format(
                        self.display_name, self.key_env_var, mode
                    ),
                    ProviderStatus.NOT_CONFIGURED,
                )
        return self.not_supported("route by " + mode)

    def status_for_feature(self, feature: str) -> ProviderStatus:
        """Return the status for a feature the active channel cannot do.

        A feature that needs the key of the user is reported as
        not_configured, so the user knows that one key would fix it.
        Everything else is reported as not_supported.
        """
        if feature in self.key_features and not self.has_own_key():
            return ProviderStatus.NOT_CONFIGURED
        return ProviderStatus.NOT_SUPPORTED

    def missing_feature_error(self, feature: str) -> ProviderError:
        """Return the error for a feature the active channel cannot do."""
        status = self.status_for_feature(feature)
        if status == ProviderStatus.NOT_CONFIGURED:
            message = "{0} needs the key {1} for {2}".format(
                self.display_name, self.key_env_var, feature
            )
        else:
            message = "{0} cannot do {1} on the {2} channel".format(
                self.display_name, feature, self.active_channel()
            )
        return ProviderError(message, status)

    def search_places(
        self,
        keyword: str,
        city: Optional[str] = None,
        near: Optional[Coord] = None,
        radius: Optional[float] = None,
        limit: int = 10,
    ) -> List[Place]:
        """Search for places. Return a list of places in GCJ-02 order."""
        raise self.not_supported("search")

    def geocode(self, address: str, city: Optional[str] = None) -> GeoResult:
        """Turn an address into coordinates in GCJ-02."""
        raise self.not_supported("geocode")

    def reverse_geocode(self, lng: float, lat: float) -> GeoResult:
        """Turn GCJ-02 coordinates into an address."""
        raise self.not_supported("reverse")

    def route(
        self,
        origin: Coord,
        destination: Coord,
        mode: str = "driving",
    ) -> Route:
        """Find a route between two GCJ-02 points."""
        raise self.not_supported("route")

    def district(self, keyword: str) -> List[Dict[str, Any]]:
        """Return the administrative districts of a keyword."""
        raise self.not_supported("district")

    def weather(self, adcode: str) -> Dict[str, Any]:
        """Return the weather of an area code."""
        raise self.not_supported("weather")

    def _as_float(self, value: Any, default: float = 0.0) -> float:
        """Return the value as a float. Return the default when it fails."""
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _dict(value: Any) -> Dict[str, Any]:
        """Return the value as a dict. Return an empty dict when it fails."""
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _text(value: Any) -> str:
        """Return the value as text. Return an empty string when it fails."""
        if value is None:
            return ""
        return str(value)

    def _parse_polyline(self, text: Any, lat_first: bool = False) -> List[Coord]:
        """Return a polyline string as a list of (lng, lat) pairs.

        The polyline of Amap and of Tencent is a string of points that are
        joined with a semicolon. The order of the points is set by the
        lat_first flag.
        """
        if not isinstance(text, str) or not text:
            return []
        points: List[Coord] = []
        for part in text.split(";"):
            part = part.strip()
            if not part or "," not in part:
                continue
            first, second = part.split(",")[:2]
            try:
                value_a = float(first)
                value_b = float(second)
            except ValueError:
                continue
            if lat_first:
                points.append((value_b, value_a))
            else:
                points.append((value_a, value_b))
        return points

    def _make_step(
        self,
        instruction: Any,
        road: Any,
        distance: Any,
        duration: Any,
        polyline: List[Coord],
        action: Any = None,
    ) -> Dict[str, Any]:
        """Return one route step in the common shape."""
        return {
            "instruction": self._text(instruction),
            "road": self._text(road),
            "action": self._text(action),
            "distance_m": self._as_float(distance),
            "duration_s": self._as_float(duration),
            "polyline": polyline,
        }
