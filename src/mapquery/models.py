"""The common data model.

Every provider answer is turned into one of these small classes, so that
the results can be compared.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

# A longitude and latitude pair. Longitude comes first.
Coord = Tuple[float, float]


class ProviderStatus(str, Enum):
    """The result of one provider call."""

    OK = "ok"
    RATE_LIMITED = "rate_limited"
    NOT_CONFIGURED = "not_configured"
    NOT_SUPPORTED = "not_supported"
    ERROR = "error"
    TIMEOUT = "timeout"

    def __str__(self) -> str:
        """Return the plain text name, such as "rate_limited"."""
        return self.value


class Channel(str, Enum):
    """The way a provider was called."""

    DIRECT = "direct"
    OFFICIAL = "official"

    def __str__(self) -> str:
        """Return the plain text name, such as "direct"."""
        return self.value


@dataclass
class Place:
    """One point of interest."""

    name: str
    address: str
    lng: float
    lat: float
    provider: str
    category: Optional[str] = None
    distance_m: Optional[float] = None
    uid: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Route:
    """One route between two places."""

    provider: str
    mode: str
    distance_m: float
    duration_s: float
    origin: Coord
    destination: Coord
    steps: List[Dict[str, Any]] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GeoResult:
    """One address and its coordinates."""

    provider: str
    address: str
    lng: float
    lat: float
    confidence: Optional[float] = None
    level: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderResult:
    """The answer of one provider call.

    The status says what happened. The data holds the parsed answer.
    """

    provider: str
    status: ProviderStatus = ProviderStatus.OK
    channel: Channel = Channel.DIRECT
    data: Any = None
    error: Optional[str] = None
    elapsed_ms: int = 0
    attempts: int = 0
    quota: Optional[Dict[str, Any]] = None
    cached: bool = False

    @property
    def is_ok(self) -> bool:
        """Return True when the provider answered with data."""
        return self.status == ProviderStatus.OK


class ProviderError(Exception):
    """An error that a provider raised.

    The status says how the call failed, so the engine can map it. The
    message is always in English. The raw reply of the provider, which can
    hold a message in another language, is kept in the raw field.
    """

    def __init__(
        self,
        message: str,
        status: ProviderStatus = ProviderStatus.ERROR,
        raw: Any = None,
    ) -> None:
        """Store the message, the status and the raw reply of the provider."""
        super().__init__(message)
        self.message = message
        self.status = status
        self.raw = raw
