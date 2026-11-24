"""The provider registry.

Every provider of the tool is listed here. The names always come back in
the same order, so the output of the tool stays stable.
"""

from typing import Dict, List, Optional, Tuple, Type

from ..config import Config
from ..http import HttpClient
from ..models import Channel
from .amap import AmapProvider
from .baidu import BaiduProvider
from .base import Provider
from .tencent import TencentProvider

# The names of the providers, in a fixed order.
PROVIDER_NAMES: Tuple[str, ...] = ("baidu", "amap", "tencent")

# The provider class of every name.
PROVIDER_CLASSES: Dict[str, Type[Provider]] = {
    "baidu": BaiduProvider,
    "amap": AmapProvider,
    "tencent": TencentProvider,
}

__all__ = [
    "PROVIDER_NAMES",
    "PROVIDER_CLASSES",
    "Provider",
    "available_providers",
    "get_provider",
]


def available_providers() -> List[str]:
    """Return the names of the providers, in a fixed order."""
    return list(PROVIDER_NAMES)


def get_provider(
    name: str,
    config: Config,
    http: HttpClient,
    channel: Optional[Channel] = None,
) -> Provider:
    """Return one provider by name.

    The name is not case sensitive. Raise ValueError for an unknown name.
    """
    key = str(name).strip().lower()
    if key not in PROVIDER_CLASSES:
        raise ValueError("unknown provider: {0}".format(name))
    return PROVIDER_CLASSES[key](config, http, channel)
