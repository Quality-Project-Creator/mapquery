"""Tests for the configuration."""

import os

import pytest

from mapquery.config import Config

try:  # Python 3.11 and later
    import tomllib as _toml_reader  # noqa: F401
except ImportError:  # pragma: no cover - only on Python 3.9 and 3.10
    try:
        import tomli as _toml_reader  # noqa: F401
    except ImportError:
        _toml_reader = None


def test_keys_are_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every key comes from its own environment variable."""
    monkeypatch.setenv("BAIDU_MAP_AK", "baidu-ak")
    monkeypatch.setenv("BAIDU_MAP_SK", "baidu-sk")
    monkeypatch.setenv("AMAP_API_KEY", "amap-key")
    monkeypatch.setenv("AMAP_SECRET_KEY", "amap-secret")
    monkeypatch.setenv("TENCENT_MAP_KEY", "tencent-key")
    monkeypatch.setenv("TENCENT_MAP_SK", "tencent-sk")

    config = Config.load()

    assert config.baidu_ak == "baidu-ak"
    assert config.baidu_sk == "baidu-sk"
    assert config.amap_key == "amap-key"
    assert config.amap_secret == "amap-secret"
    assert config.tencent_key == "tencent-key"
    assert config.tencent_sk == "tencent-sk"


def test_the_defaults_are_used_when_nothing_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """The defaults are the ones from the plan."""
    for name in (
        "BAIDU_MAP_AK",
        "BAIDU_MAP_SK",
        "AMAP_API_KEY",
        "AMAP_SECRET_KEY",
        "TENCENT_MAP_KEY",
        "TENCENT_MAP_SK",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MAPQUERY_CONFIG", os.path.join(os.sep, "no", "such", "file.toml"))

    config = Config.load()

    assert config.baidu_ak == ""
    assert config.amap_key == ""
    assert config.tencent_key == ""
    assert config.timeout == 10.0
    assert config.retries == 2
    assert config.jobs == 8
    assert config.rate_limits["baidu"] == 20.0
    assert config.rate_limits["amap"] == 3.0
    assert config.rate_limits["tencent"] == 5.0


def test_the_config_file_is_used(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """The config file fills in what the environment does not set."""
    if _toml_reader is None:
        pytest.skip("no TOML reader on this Python")

    for name in ("BAIDU_MAP_AK", "BAIDU_MAP_SK"):
        monkeypatch.delenv(name, raising=False)

    path = tmp_path / "config.toml"
    path.write_text(
        "[baidu]\nak = 'file-ak'\nsk = 'file-sk'\n\n[rate_limits]\namap = 2.5\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MAPQUERY_CONFIG", str(path))

    config = Config.load()

    assert config.baidu_ak == "file-ak"
    assert config.baidu_sk == "file-sk"
    assert config.rate_limits["amap"] == 2.5
    assert config.rate_limits["baidu"] == 20.0


def test_the_environment_wins_over_the_file(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """A key in the environment is never replaced by the file."""
    if _toml_reader is None:
        pytest.skip("no TOML reader on this Python")

    path = tmp_path / "config.toml"
    path.write_text("[baidu]\nak = 'file-ak'\n", encoding="utf-8")
    monkeypatch.setenv("MAPQUERY_CONFIG", str(path))
    monkeypatch.setenv("BAIDU_MAP_AK", "env-ak")

    config = Config.load()

    assert config.baidu_ak == "env-ak"


def test_mask_key_shows_only_the_last_four_characters() -> None:
    """A key is never shown in full."""
    assert Config.mask_key("abcdef1234f3a9") == "...f3a9"
    assert Config.mask_key("1234") == "****"
    assert Config.mask_key("") == ""


def test_masked_keys_never_hold_a_full_key() -> None:
    """The masked view is safe to print."""
    config = Config(
        baidu_ak="baidu-ak-value",
        amap_key="amap-key-value",
        tencent_key="tencent-key-value",
    )
    masked = config.masked_keys()

    assert masked["baidu_ak"] == "...alue"
    assert "baidu-ak-value" not in masked.values()


def test_the_simple_reader_reads_the_config_file(tmp_path) -> None:
    """The config file can be read without a TOML library.

    Python 3.9 has no TOML reader in the standard library and the
    project has no other dependency, so the simple reader is used there.
    """
    from mapquery.config import _load_simple_toml

    path = tmp_path / "config.toml"
    path.write_text(
        '# a comment\n'
        'timeout = 12\n'
        'jobs = 4\n'
        '\n'
        '[baidu]\n'
        'ak = "file-ak"\n'
        '\n'
        '[rate_limits]\n'
        'amap = 2.5\n',
        encoding="utf-8",
    )

    data = _load_simple_toml(str(path))

    assert data["timeout"] == 12
    assert data["jobs"] == 4
    assert data["baidu"]["ak"] == "file-ak"
    assert data["rate_limits"]["amap"] == 2.5


def test_a_broken_config_file_is_ignored_with_a_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path, capsys: pytest.CaptureFixture
) -> None:
    """A file that cannot be parsed is named and skipped.

    The tool keeps working, but the user hears about the file, because
    every key in it is gone.
    """
    path = tmp_path / "config.toml"
    path.write_text('[amap]\nkey = "abc"def"\n', encoding="utf-8")
    monkeypatch.setenv("MAPQUERY_CONFIG", str(path))

    config = Config.load()

    assert config.amap_key == ""
    error = capsys.readouterr().err
    assert str(path) in error
    assert "ignored" in error


def test_a_good_config_file_is_not_complained_about(
    monkeypatch: pytest.MonkeyPatch, tmp_path, capsys: pytest.CaptureFixture
) -> None:
    """A file that can be parsed is read without a warning."""
    path = tmp_path / "config.toml"
    path.write_text('[amap]\nkey = "good-key"\n', encoding="utf-8")
    monkeypatch.setenv("MAPQUERY_CONFIG", str(path))

    config = Config.load()

    assert config.amap_key == "good-key"
    assert capsys.readouterr().err == ""


def test_the_connect_timeout_is_a_setting(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """The connect timeout can be set in the config file."""
    path = tmp_path / "config.toml"
    path.write_text("connect_timeout = 1.5\n", encoding="utf-8")
    monkeypatch.setenv("MAPQUERY_CONFIG", str(path))

    config = Config.load()

    assert config.connect_timeout == 1.5


def test_the_connect_timeout_has_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """The plan asks for a connect timeout of 3.1 seconds."""
    monkeypatch.setenv("MAPQUERY_CONFIG", os.path.join(os.sep, "no", "such", "file.toml"))

    config = Config.load()

    assert config.connect_timeout == 3.1


def test_the_cache_folder_can_come_from_the_environment(monkeypatch, tmp_path) -> None:
    """The environment wins over the config file for the cache folder."""
    monkeypatch.setenv("MAPQUERY_CACHE_DIR", str(tmp_path / "cache"))

    config = Config.load()

    assert config.cache_dir == str(tmp_path / "cache")
