"""Configuration for mapquery.

Keys are read from the environment first. Then an optional TOML file is
read. The file only fills in what the environment does not set.

A file that cannot be parsed is not used at all. The tool says so and
keeps working, so a broken file never silently takes the keys away.
"""

import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .compare import MATCH_DISTANCE_M, MATCH_NAME_RATIO, SAME_PLACE_DISTANCE_M

# The name of the environment variable that holds the config file path.
CONFIG_PATH_ENV = "MAPQUERY_CONFIG"

# The name of the environment variable that holds the cache folder.
CACHE_DIR_ENV = "MAPQUERY_CACHE_DIR"

# The default config file location.
DEFAULT_CONFIG_PATH = "~/.config/mapquery/config.toml"

# The default cache folder.
DEFAULT_CACHE_DIR = "~/.cache/mapquery"

# Default requests per second, one number per provider.
DEFAULT_RATE_LIMITS = {
    "baidu": 20.0,
    "amap": 3.0,
    "tencent": 5.0,
}

# The connect timeout of one request, in seconds. The read timeout is the
# timeout of the config.
DEFAULT_CONNECT_TIMEOUT = 3.1

# Environment variable name for every key.
ENV_VARS = {
    "baidu_ak": "BAIDU_MAP_AK",
    "baidu_sk": "BAIDU_MAP_SK",
    "amap_key": "AMAP_API_KEY",
    "amap_secret": "AMAP_SECRET_KEY",
    "tencent_key": "TENCENT_MAP_KEY",
    "tencent_sk": "TENCENT_MAP_SK",
}

# The environment variable that holds the key of every provider.
PROVIDER_KEY_ENV = {
    "baidu": "BAIDU_MAP_AK",
    "amap": "AMAP_API_KEY",
    "tencent": "TENCENT_MAP_KEY",
}


class ConfigFileError(Exception):
    """The config file exists but cannot be parsed."""


def warn_about_config_file(path: str, error: Exception) -> None:
    """Say that the config file is broken and that it is ignored."""
    print(
        "Warning: the config file {0} cannot be parsed, so it is ignored. ({1})".format(
            path, error
        ),
        file=sys.stderr,
    )


def _toml_reader() -> Any:
    """Return the TOML reader of this Python. Return None when there is none."""
    try:
        import tomllib  # type: ignore[import-not-found]
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            return None
    return tomllib


def read_config_file(path: str) -> Dict[str, Any]:
    """Return the data of the config file.

    A file that is not there gives an empty dict. A file that cannot be
    parsed raises ConfigFileError, so the caller can say so and keep
    working.
    """
    module = _toml_reader()
    if module is None:
        # Python 3.9 has no TOML reader in the standard library and the
        # project has no other dependency, so the simple reader below is
        # used.
        return _load_simple_toml(path)

    try:
        with open(path, "rb") as handle:
            return dict(module.load(handle))
    except OSError:
        return {}
    except ValueError as exc:
        raise ConfigFileError("the file is not valid TOML: {0}".format(exc))


def _load_toml(path: str) -> Dict[str, Any]:
    """Read a TOML file. Return an empty dict when it cannot be read."""
    try:
        return read_config_file(path)
    except ConfigFileError as exc:
        warn_about_config_file(path, exc)
        return {}


def _load_simple_toml(path: str) -> Dict[str, Any]:
    """Read a TOML file without a TOML library.

    Only the parts that the config file uses are understood: a table name
    in square brackets and "name = value" lines. The value is a number
    when it looks like one, a true or a false when it says so, and text
    otherwise.

    A value whose quote is not closed is a broken file. It raises
    ConfigFileError, the same way the TOML library does.
    """
    data: Dict[str, Any] = {}
    section: Dict[str, Any] = data
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return {}

    for line in lines:
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if text.startswith("[") and text.endswith("]"):
            name = text[1:-1].strip()
            block = data.get(name)
            if not isinstance(block, dict):
                block = {}
                data[name] = block
            section = block
            continue
        if "=" not in text:
            continue
        name, _, value = text.partition("=")
        value = value.strip()
        if value[:1] in ('"', "'"):
            if len(value) < 2 or value[-1] != value[0]:
                raise ConfigFileError(
                    "the value of {0} is not closed".format(name.strip())
                )
        section[name.strip()] = _simple_value(value)

    return data


def _simple_value(text: str) -> Any:
    """Return the value of one line of the simple TOML reader."""
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text[1:-1]
    if text in ("true", "false"):
        return text == "true"
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def _as_float(value: Any, fallback: float) -> float:
    """Return the value as a float. Return the fallback when it fails."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _as_int(value: Any, fallback: int) -> int:
    """Return the value as an int. Return the fallback when it fails."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _pick(data: Dict[str, Any], section: str, names: tuple) -> Optional[Any]:
    """Return a value from a section of the config file.

    The section is tried first. Then the top level of the file.
    """
    block = data.get(section)
    if isinstance(block, dict):
        for name in names:
            if name in block:
                return block[name]
    for name in names:
        if name in data:
            return data[name]
    return None


@dataclass
class Config:
    """All settings of one run."""

    baidu_ak: str = ""
    baidu_sk: str = ""
    amap_key: str = ""
    amap_secret: str = ""
    tencent_key: str = ""
    tencent_sk: str = ""
    timeout: float = 10.0
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT
    retries: int = 2
    jobs: int = 8
    cache_dir: str = DEFAULT_CACHE_DIR
    rate_limits: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_RATE_LIMITS))
    cluster_radius: float = MATCH_DISTANCE_M
    name_ratio: float = MATCH_NAME_RATIO
    same_place_radius: float = SAME_PLACE_DISTANCE_M

    @staticmethod
    def mask_key(value: str) -> str:
        """Return a short safe form of a key, such as "...f3a9"."""
        if not value:
            return ""
        if len(value) <= 4:
            return "****"
        return "..." + value[-4:]

    def masked_keys(self) -> Dict[str, str]:
        """Return every key in masked form. Safe to print."""
        return {
            "baidu_ak": self.mask_key(self.baidu_ak),
            "baidu_sk": self.mask_key(self.baidu_sk),
            "amap_key": self.mask_key(self.amap_key),
            "amap_secret": self.mask_key(self.amap_secret),
            "tencent_key": self.mask_key(self.tencent_key),
            "tencent_sk": self.mask_key(self.tencent_sk),
        }

    def key_for(self, provider: str) -> str:
        """Return the main key of a provider. Return an empty string if there is none."""
        keys = {
            "baidu": self.baidu_ak,
            "amap": self.amap_key,
            "tencent": self.tencent_key,
        }
        return keys.get(provider, "")

    @classmethod
    def load(cls) -> "Config":
        """Build a config from the environment and the config file."""
        config = cls()

        path = os.environ.get(CONFIG_PATH_ENV) or DEFAULT_CONFIG_PATH
        path = os.path.expanduser(path)
        data = _load_toml(path) if path else {}

        config.baidu_ak = os.environ.get(ENV_VARS["baidu_ak"]) or _as_text(
            _pick(data, "baidu", ("ak", "baidu_ak"))
        )
        config.baidu_sk = os.environ.get(ENV_VARS["baidu_sk"]) or _as_text(
            _pick(data, "baidu", ("sk", "baidu_sk"))
        )
        config.amap_key = os.environ.get(ENV_VARS["amap_key"]) or _as_text(
            _pick(data, "amap", ("key", "amap_key"))
        )
        config.amap_secret = os.environ.get(ENV_VARS["amap_secret"]) or _as_text(
            _pick(data, "amap", ("secret", "amap_secret"))
        )
        config.tencent_key = os.environ.get(ENV_VARS["tencent_key"]) or _as_text(
            _pick(data, "tencent", ("key", "tencent_key"))
        )
        config.tencent_sk = os.environ.get(ENV_VARS["tencent_sk"]) or _as_text(
            _pick(data, "tencent", ("sk", "tencent_sk"))
        )

        config.cluster_radius = _as_float(
            data.get("cluster_radius"), config.cluster_radius
        )
        config.name_ratio = _as_float(data.get("name_ratio"), config.name_ratio)
        config.same_place_radius = _as_float(
            data.get("same_place_radius"), config.same_place_radius
        )

        config.timeout = _as_float(data.get("timeout"), config.timeout)
        config.connect_timeout = _as_float(
            data.get("connect_timeout"), config.connect_timeout
        )
        config.retries = _as_int(data.get("retries"), config.retries)
        config.jobs = _as_int(data.get("jobs"), config.jobs)

        cache_dir = os.environ.get(CACHE_DIR_ENV) or data.get("cache_dir")
        if isinstance(cache_dir, str) and cache_dir:
            config.cache_dir = os.path.expanduser(cache_dir)
        else:
            config.cache_dir = os.path.expanduser(DEFAULT_CACHE_DIR)

        limits = dict(DEFAULT_RATE_LIMITS)
        block = data.get("rate_limits")
        if isinstance(block, dict):
            for name, value in block.items():
                limits[str(name)] = _as_float(value, limits.get(str(name), 0.0))
        config.rate_limits = limits

        return config


def _as_text(value: Any) -> str:
    """Return the value as text. Return an empty string when it fails."""
    if value is None:
        return ""
    return str(value)
