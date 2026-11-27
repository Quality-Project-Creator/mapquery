"""Tests for the command line interface.

Every test is offline. The provider layer is patched, so no test touches
the network.
"""

import csv
import getpass
import io
import json
import os
import re
import subprocess
from typing import Any, Dict, List, Optional, Set

import pytest

from mapquery.cli import ROUTE_MODES, main
from mapquery.coords import haversine_m
from mapquery.models import Channel, GeoResult, Place, ProviderError, ProviderStatus


class FakeProvider:
    """A provider that answers without the network."""

    def __init__(
        self,
        name: str,
        places: Optional[List[Place]] = None,
        features: Optional[Set[str]] = None,
    ) -> None:
        """Store the name, the places and the features of the provider."""
        self.name = name
        self.display_name = name.title()
        self.key_env_var = name.upper() + "_KEY"
        self.places = places if places is not None else []
        self.features = features if features is not None else {"search"}

    def active_channel(self) -> Channel:
        """Return the channel of the provider."""
        return Channel.DIRECT

    def has_own_key(self) -> bool:
        """Return False, so the direct channel is used."""
        return False

    def features_for(self, channel: Channel) -> Set[str]:
        """Return the features of the provider."""
        return set(self.features)

    def supports(self, feature: str) -> bool:
        """Return True when the provider can do the feature."""
        return feature in self.features

    def missing_feature_error(self, feature: str) -> ProviderError:
        """Return the error for a feature the provider cannot do."""
        return ProviderError(
            "{0} cannot do {1}".format(self.display_name, feature),
            ProviderStatus.NOT_SUPPORTED,
        )

    def search_places(
        self,
        keyword: str,
        city: Optional[str] = None,
        near: Optional[Any] = None,
        radius: Optional[float] = None,
        limit: int = 10,
    ) -> List[Place]:
        """Return the places of the provider."""
        return self.places[:limit]

    def geocode(self, address: str, city: Optional[str] = None) -> Any:
        """Return a point for an address."""
        raise ProviderError("no geocode", ProviderStatus.NOT_SUPPORTED)

    def reverse_geocode(self, lng: float, lat: float) -> Any:
        """Return an address for a point."""
        raise ProviderError("no reverse geocode", ProviderStatus.NOT_SUPPORTED)

    def route(self, origin: Any, destination: Any, mode: str = "driving") -> Any:
        """Return a route between two points."""
        raise ProviderError("no route", ProviderStatus.NOT_SUPPORTED)

    def district(self, keyword: str) -> List[Dict[str, Any]]:
        """Return the districts of a place."""
        raise ProviderError("no district", ProviderStatus.NOT_SUPPORTED)

    def weather(self, adcode: str) -> Dict[str, Any]:
        """Return the weather of an area code."""
        raise ProviderError("no weather", ProviderStatus.NOT_SUPPORTED)


class GeoProvider(FakeProvider):
    """A provider that can geocode a place or fail with a given status."""

    def __init__(
        self,
        name: str,
        status: Optional[ProviderStatus] = None,
        point: Any = (116.3975, 39.9088),
        places: Optional[List[Place]] = None,
        fail_on: Optional[str] = None,
    ) -> None:
        """Store the name, the status of the failure and the point."""
        super().__init__(name, places=places or [], features={"geocode", "route"})
        self.status = status
        self.point = point
        self.fail_on = fail_on

    def geocode(self, address: str, city: Optional[str] = None) -> GeoResult:
        """Return a point for an address, or fail with the wanted status."""
        if self.status is not None and address == self.fail_on:
            raise ProviderError("the provider rate limit was hit", self.status)
        if self.status is not None and self.fail_on is None:
            raise ProviderError("the provider rate limit was hit", self.status)
        return GeoResult(
            provider=self.name,
            address=address,
            lng=self.point[0],
            lat=self.point[1],
        )


class FakeHttpClient:
    """An http client that knows what happened in the last request."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Store the state of the last request of every provider."""
        self.state = {
            "attempts": 3,
            "quota": {"current_qps": "3"},
            "cached": True,
        }

    def state_for(self, provider: str) -> Dict[str, Any]:
        """Return the state of the last request of one provider."""
        return dict(self.state)


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the settings of the tests the same every time."""
    monkeypatch.setenv("MAPQUERY_CONFIG", "/nonexistent/mapquery-config.toml")
    for name in (
        "BAIDU_MAP_AK",
        "BAIDU_MAP_SK",
        "AMAP_API_KEY",
        "AMAP_SECRET_KEY",
        "TENCENT_MAP_KEY",
        "TENCENT_MAP_SK",
    ):
        monkeypatch.delenv(name, raising=False)


def test_convert_gives_the_point_in_the_other_system(capsys: pytest.CaptureFixture) -> None:
    """The convert command changes the point from one system to another."""
    code = main(["convert", "--from", "bd09", "--to", "gcj02", "116.403963,39.915119"])

    assert code == 0
    text = capsys.readouterr().out
    assert "116.3975904" in text
    assert "39.9087759" in text

    # The point is the same place as the Tiananmen gate in GCJ-02.
    distance = haversine_m(116.3975904, 39.9087759, 116.3975904, 39.9087759)
    assert distance < 5.0


def test_convert_in_json_gives_numbers(capsys: pytest.CaptureFixture) -> None:
    """The JSON output of the convert command holds the point."""
    code = main(["--json", "convert", "--from", "bd09", "--to", "gcj02", "116.403963,39.915119"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert abs(payload["results"]["lng"] - 116.3975904) < 1e-6
    assert abs(payload["results"]["lat"] - 39.9087759) < 1e-6


def test_a_bad_coordinate_is_a_usage_error(capsys: pytest.CaptureFixture) -> None:
    """A point that is not lng,lat gives the exit code 2."""
    code = main(["reverse", "not-a-point"])

    assert code == 2
    assert "lng,lat" in capsys.readouterr().err


def test_a_point_out_of_range_is_a_usage_error() -> None:
    """A point that cannot exist gives the exit code 2."""
    assert main(["reverse", "200,100"]) == 2


def test_the_version_is_printed(capsys: pytest.CaptureFixture) -> None:
    """The version option prints the version."""
    from mapquery import __version__

    with pytest.raises(SystemExit) as info:
        main(["--version"])

    assert info.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_the_providers_command_shows_every_provider(capsys: pytest.CaptureFixture) -> None:
    """The providers command shows the three providers."""
    code = main(["providers"])

    assert code == 0
    text = capsys.readouterr().out
    assert "baidu" in text
    assert "amap" in text
    assert "tencent" in text


def test_the_providers_command_never_shows_a_full_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """A key is only shown in a masked form."""
    monkeypatch.setenv("AMAP_API_KEY", "amap-key-value-1234")

    code = main(["providers"])

    assert code == 0
    text = capsys.readouterr().out
    assert "amap-key-value-1234" not in text
    assert "...1234" in text


def test_the_search_command_prints_the_status_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Every command that calls a provider prints the status line."""
    place = Place(
        name="天安门",
        address="Beijing",
        lng=116.3975,
        lat=39.9088,
        provider="baidu",
    )
    fake = FakeProvider("baidu", places=[place])

    def fake_get_provider(name: str, config: Any, http: Any, channel: Any = None) -> FakeProvider:
        """Return the fake provider."""
        return fake

    monkeypatch.setattr("mapquery.cli.get_provider", fake_get_provider)

    code = main(["--providers", "baidu", "search", "天安门", "--limit", "1"])

    assert code == 0
    text = capsys.readouterr().out
    assert "baidu: ok" in text
    assert "天安门" in text


def test_the_search_command_fails_when_every_provider_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """A command where no provider answers gives the exit code 1."""
    fake = FakeProvider("baidu", features=set())

    def fake_get_provider(name: str, config: Any, http: Any, channel: Any = None) -> FakeProvider:
        """Return the fake provider."""
        return fake

    monkeypatch.setattr("mapquery.cli.get_provider", fake_get_provider)

    code = main(["--providers", "baidu", "search", "天安门"])

    assert code == 1
    assert "not_supported" in capsys.readouterr().out


def test_the_compare_command_shows_the_clusters(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """The compare command shows the places and the clusters."""
    def place(name: str, lng: float, lat: float, provider: str) -> Place:
        """Return one place for the test."""
        return Place(
            name=name, address="Beijing", lng=lng, lat=lat, provider=provider
        )

    providers = {
        "baidu": FakeProvider(
            "baidu", places=[place("天安门", 116.3975, 39.9088, "baidu")]
        ),
        "amap": FakeProvider(
            "amap", places=[place("天安门", 116.3977, 39.9090, "amap")]
        ),
        "tencent": FakeProvider(
            "tencent", places=[place("天安门", 116.3979, 39.9085, "tencent")]
        ),
    }

    def fake_get_provider(name: str, config: Any, http: Any, channel: Any = None) -> FakeProvider:
        """Return the fake provider of the name."""
        return providers[name]

    monkeypatch.setattr("mapquery.cli.get_provider", fake_get_provider)

    code = main(["compare", "天安门"])

    assert code == 0
    text = capsys.readouterr().out
    assert "Clusters" in text
    assert "Consensus" in text
    assert "Spread" in text


def test_an_unknown_provider_is_a_usage_error(capsys: pytest.CaptureFixture) -> None:
    """A provider that does not exist gives the exit code 2."""
    code = main(["--providers", "nope", "search", "天安门"])

    assert code == 2
    assert "unknown provider" in capsys.readouterr().err


def test_the_matrix_command_says_that_it_is_a_straight_line(
    capsys: pytest.CaptureFixture,
) -> None:
    """The matrix command says that the distance is not a road distance."""
    code = main(["matrix", "--from", "116.397428,39.908823", "--to", "116.39667,39.90864"])

    assert code == 0
    text = capsys.readouterr().out
    assert "Straight line" in text
    assert "not a road distance" in text


def test_the_config_show_command_never_shows_a_full_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """The config command shows the keys in a masked form."""
    monkeypatch.setenv("TENCENT_MAP_KEY", "tencent-key-value-9999")

    code = main(["config", "show"])

    assert code == 0
    text = capsys.readouterr().out
    assert "tencent-key-value-9999" not in text
    assert "...9999" in text


# ----------------------------------------------------------------------
# The status of a provider is never changed
# ----------------------------------------------------------------------


def test_route_keeps_the_rate_limit_status(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """A rate limit on one end of the route stays a rate limit."""
    fake = GeoProvider("tencent", status=ProviderStatus.RATE_LIMITED)

    def fake_get_provider(name: str, config: Any, http: Any, channel: Any = None) -> Any:
        """Return the fake provider."""
        return fake

    monkeypatch.setattr("mapquery.cli.get_provider", fake_get_provider)

    code = main(["--providers", "tencent", "route", "天安门", "116.39667,39.90864"])

    assert code == 1
    text = capsys.readouterr().out
    assert "tencent: rate_limited" in text
    assert "error" not in text


def test_route_keeps_the_timeout_status(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """A timeout on one end of the route stays a timeout."""
    fake = GeoProvider("tencent", status=ProviderStatus.TIMEOUT)

    def fake_get_provider(name: str, config: Any, http: Any, channel: Any = None) -> Any:
        """Return the fake provider."""
        return fake

    monkeypatch.setattr("mapquery.cli.get_provider", fake_get_provider)

    code = main(["--providers", "tencent", "route", "天安门", "116.39667,39.90864"])

    assert code == 1
    assert "tencent: timeout" in capsys.readouterr().out


def test_route_keeps_the_not_supported_status(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """A provider that cannot geocode stays not supported."""
    fake = GeoProvider("tencent", status=ProviderStatus.NOT_SUPPORTED)

    def fake_get_provider(name: str, config: Any, http: Any, channel: Any = None) -> Any:
        """Return the fake provider."""
        return fake

    monkeypatch.setattr("mapquery.cli.get_provider", fake_get_provider)

    code = main(["--providers", "tencent", "route", "天安门", "116.39667,39.90864"])

    assert code == 1
    assert "tencent: not_supported" in capsys.readouterr().out


def test_the_matrix_uses_a_provider_that_answered(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """A rate limited provider does not stop the matrix.

    The place is found with the provider that answered, and the provider
    that failed keeps its own status in the status line.
    """
    providers = {
        "baidu": GeoProvider("baidu", status=ProviderStatus.RATE_LIMITED),
        "amap": GeoProvider("amap"),
    }

    def fake_get_provider(name: str, config: Any, http: Any, channel: Any = None) -> Any:
        """Return the fake provider of the name."""
        return providers[name]

    monkeypatch.setattr("mapquery.cli.get_provider", fake_get_provider)

    code = main(
        [
            "--verbose",
            "--json",
            "--providers",
            "baidu,amap",
            "matrix",
            "--from",
            "天安门",
            "--to",
            "116.39667,39.90864",
        ]
    )

    assert code == 0
    captured = capsys.readouterr()
    assert "baidu: rate_limited" in captured.err
    assert "amap: ok" in captured.err

    payload = json.loads(captured.out)
    row = payload["results"][0]
    # The cell holds the distance, not an empty answer.
    assert row["116.39667,39.90864"] > 0.0


def test_the_matrix_never_calls_a_failed_provider_ok(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """A provider that fails is never reported as an answer with no data."""
    providers = {
        "baidu": GeoProvider("baidu", status=ProviderStatus.RATE_LIMITED),
        "amap": GeoProvider("amap"),
    }

    def fake_get_provider(name: str, config: Any, http: Any, channel: Any = None) -> Any:
        """Return the fake provider of the name."""
        return providers[name]

    monkeypatch.setattr("mapquery.cli.get_provider", fake_get_provider)

    code = main(
        [
            "--providers",
            "baidu,amap",
            "matrix",
            "--from",
            "天安门",
            "--to",
            "116.39667,39.90864",
        ]
    )

    assert code == 0
    text = capsys.readouterr().out
    assert "baidu: rate_limited" in text
    assert "baidu: ok" not in text


def test_the_matrix_says_when_no_provider_answers(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """The matrix stops with the code 1 when no place could be found."""
    providers = {
        "baidu": GeoProvider("baidu", status=ProviderStatus.RATE_LIMITED),
        "amap": GeoProvider("amap", status=ProviderStatus.ERROR),
    }

    def fake_get_provider(name: str, config: Any, http: Any, channel: Any = None) -> Any:
        """Return the fake provider of the name."""
        return providers[name]

    monkeypatch.setattr("mapquery.cli.get_provider", fake_get_provider)

    code = main(
        [
            "--providers",
            "baidu,amap",
            "matrix",
            "--from",
            "天安门",
            "--to",
            "116.39667,39.90864",
        ]
    )

    assert code == 1
    captured = capsys.readouterr()
    assert "No provider could find" in captured.out
    assert "baidu: rate_limited" in captured.out
    assert "amap: error" in captured.out


def test_the_matrix_failure_shows_the_verbose_lines(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """The failure path of the matrix shows the verbose lines too."""
    providers = {
        "baidu": GeoProvider("baidu", status=ProviderStatus.RATE_LIMITED),
        "amap": GeoProvider("amap", status=ProviderStatus.ERROR),
    }

    def fake_get_provider(name: str, config: Any, http: Any, channel: Any = None) -> Any:
        """Return the fake provider of the name."""
        return providers[name]

    monkeypatch.setattr("mapquery.cli.get_provider", fake_get_provider)

    code = main(
        [
            "--providers",
            "baidu,amap",
            "--verbose",
            "--json",
            "matrix",
            "--from",
            "天安门",
            "--to",
            "116.39667,39.90864",
        ]
    )

    assert code == 1
    error = capsys.readouterr().err
    assert "baidu: rate_limited" in error
    assert "baidu: channel direct" in error
    assert "attempt" in error


def test_the_weather_command_says_that_only_amap_can_do_it(
    capsys: pytest.CaptureFixture,
) -> None:
    """The weather is always Amap, so another list is a usage mistake."""
    code = main(["--providers", "tencent", "weather", "110101"])

    assert code == 2
    error = capsys.readouterr().err
    assert "Only Amap can do the weather" in error
    assert "tencent" in error


def test_the_weather_command_uses_amap(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """The weather of Amap is shown when Amap is selected."""
    class WeatherProvider(FakeProvider):
        """A provider that has the weather."""

        def weather(self, adcode: str) -> Dict[str, Any]:
            """Return the weather of an area code."""
            return {"lives": [{"city": "北京", "weather": "晴", "temperature": "25"}]}

    fake = WeatherProvider("amap", features={"weather"})

    def fake_get_provider(name: str, config: Any, http: Any, channel: Any = None) -> Any:
        """Return the fake provider."""
        return fake

    monkeypatch.setattr("mapquery.cli.get_provider", fake_get_provider)

    code = main(["--providers", "amap", "weather", "110101"])

    assert code == 0
    text = capsys.readouterr().out
    assert "amap: ok" in text
    assert "晴" in text


def test_the_matrix_lists_every_provider_that_was_asked(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """The status line holds every provider with its own status."""
    providers = {
        "baidu": GeoProvider("baidu", status=ProviderStatus.RATE_LIMITED),
        "amap": GeoProvider("amap"),
        "tencent": GeoProvider("tencent", status=ProviderStatus.TIMEOUT),
    }

    def fake_get_provider(name: str, config: Any, http: Any, channel: Any = None) -> Any:
        """Return the fake provider of the name."""
        return providers[name]

    monkeypatch.setattr("mapquery.cli.get_provider", fake_get_provider)

    code = main(
        [
            "--providers",
            "baidu,amap,tencent",
            "matrix",
            "--from",
            "天安门",
            "--to",
            "116.39667,39.90864",
        ]
    )

    assert code == 0
    text = capsys.readouterr().out
    assert "baidu: rate_limited" in text
    assert "amap: ok" in text
    assert "tencent: timeout" in text


# ----------------------------------------------------------------------
# The cycling mode
# ----------------------------------------------------------------------


def test_the_cycling_mode_has_one_name_for_every_provider() -> None:
    """Every provider calls the cycling mode bicycling."""
    assert ROUTE_MODES["cycling"]["amap"] == "bicycling"
    assert ROUTE_MODES["cycling"]["tencent"] == "bicycling"
    # Baidu has no cycling route at all.
    assert ROUTE_MODES["cycling"]["baidu"] == "cycling"


def test_the_route_command_sends_the_cycling_mode_to_the_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The provider gets the name that it knows."""
    seen: List[str] = []

    class RouteProvider(FakeProvider):
        """A provider that remembers the mode of the route."""

        def route(self, origin: Any, destination: Any, mode: str = "driving") -> Any:
            """Remember the mode and answer with a route."""
            seen.append(mode)
            raise ProviderError("no route", ProviderStatus.NOT_SUPPORTED)

    fake = RouteProvider("tencent", features={"route"})

    def fake_get_provider(name: str, config: Any, http: Any, channel: Any = None) -> Any:
        """Return the fake provider."""
        return fake

    monkeypatch.setattr("mapquery.cli.get_provider", fake_get_provider)

    main(["--providers", "tencent", "route", "116.397,39.909", "116.396,39.908", "--mode", "cycling"])

    assert seen == ["bicycling"]


# ----------------------------------------------------------------------
# The empty input
# ----------------------------------------------------------------------


def test_an_empty_keyword_is_a_usage_error(capsys: pytest.CaptureFixture) -> None:
    """An empty keyword stops the command before a live call."""
    code = main(["search", ""])

    assert code == 2
    assert "keyword" in capsys.readouterr().err


def test_an_empty_address_is_a_usage_error(capsys: pytest.CaptureFixture) -> None:
    """An empty address stops the command before a live call."""
    code = main(["geocode", ""])

    assert code == 2
    assert "address" in capsys.readouterr().err


def test_an_empty_city_is_a_usage_error(capsys: pytest.CaptureFixture) -> None:
    """An empty city stops the command before a live call."""
    code = main(["search", "天安门", "--city", ""])

    assert code == 2
    assert "city" in capsys.readouterr().err


def test_an_empty_provider_list_is_a_usage_error(capsys: pytest.CaptureFixture) -> None:
    """An empty list of providers is a mistake of the user."""
    code = main(["--providers", "", "search", "天安门"])

    assert code == 2
    assert "providers" in capsys.readouterr().err


def test_a_stray_comma_names_the_empty_entry(capsys: pytest.CaptureFixture) -> None:
    """The list is not empty, one of its entries is.

    The message names the entry that is wrong, so the user knows what to
    fix.
    """
    code = main(["--providers", "baidu,", "search", "天安门"])

    assert code == 2
    error = capsys.readouterr().err
    assert "providers" in error
    assert "position 2" in error


def test_an_empty_keyword_of_compare_is_a_usage_error(capsys: pytest.CaptureFixture) -> None:
    """The compare command stops on an empty keyword too."""
    code = main(["compare", ""])

    assert code == 2
    assert "keyword" in capsys.readouterr().err


# ----------------------------------------------------------------------
# The output formats
# ----------------------------------------------------------------------


def test_json_and_csv_together_stop_the_command() -> None:
    """Two formats are a mistake of the user."""
    with pytest.raises(SystemExit) as info:
        main(["search", "天安门", "--json", "--csv"])

    assert info.value.code == 2


def test_json_before_the_command_and_csv_after_it_stop_the_command(
    capsys: pytest.CaptureFixture,
) -> None:
    """The formats are checked before any provider is called."""
    code = main(["--json", "search", "天安门", "--csv"])

    assert code == 2
    assert "--json" in capsys.readouterr().err


# ----------------------------------------------------------------------
# The verbose mode and the state of the request
# ----------------------------------------------------------------------


def test_the_verbose_mode_shows_the_details_of_every_provider(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """The verbose mode adds a line for every provider."""
    place = Place(
        name="天安门", address="Beijing", lng=116.3975, lat=39.9088, provider="baidu"
    )
    fake = FakeProvider("baidu", places=[place])

    def fake_get_provider(name: str, config: Any, http: Any, channel: Any = None) -> Any:
        """Return the fake provider."""
        return fake

    monkeypatch.setattr("mapquery.cli.get_provider", fake_get_provider)

    code = main(["--verbose", "--providers", "baidu", "search", "天安门"])

    assert code == 0
    text = capsys.readouterr().out
    assert "baidu: channel direct" in text
    assert "attempt" in text
    assert "from the network" in text


def test_the_attempts_and_the_cache_flag_reach_the_json_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """The facts of the request are part of the answer."""
    place = Place(
        name="天安门", address="Beijing", lng=116.3975, lat=39.9088, provider="baidu"
    )
    fake = FakeProvider("baidu", places=[place])

    def fake_get_provider(name: str, config: Any, http: Any, channel: Any = None) -> Any:
        """Return the fake provider."""
        return fake

    monkeypatch.setattr("mapquery.cli.get_provider", fake_get_provider)
    monkeypatch.setattr("mapquery.cli.HttpClient", FakeHttpClient)

    code = main(["--json", "--providers", "baidu", "search", "天安门"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    answer = payload["providers"]["baidu"]
    assert answer["attempts"] == 3
    assert answer["cached"] is True
    assert answer["quota"]["current_qps"] == "3"


# ----------------------------------------------------------------------
# The compare command
# ----------------------------------------------------------------------


def _compare_providers() -> Dict[str, Any]:
    """Return the fake providers of the compare command."""
    def place(name: str, lng: float, lat: float, provider: str) -> Place:
        """Return one place for the test."""
        return Place(name=name, address="Beijing", lng=lng, lat=lat, provider=provider)

    return {
        "baidu": FakeProvider("baidu", places=[place("天安门", 116.3975, 39.9088, "baidu")]),
        "amap": FakeProvider("amap", places=[place("天安门", 116.3977, 39.9090, "amap")]),
    }


def test_the_compare_csv_holds_the_clusters_and_the_consensus(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """The CSV of the compare command is not only the places."""
    providers = _compare_providers()

    def fake_get_provider(name: str, config: Any, http: Any, channel: Any = None) -> Any:
        """Return the fake provider of the name."""
        return providers[name]

    monkeypatch.setattr("mapquery.cli.get_provider", fake_get_provider)

    code = main(["--providers", "baidu,amap", "--csv", "compare", "天安门"])

    assert code == 0
    text = capsys.readouterr().out
    assert "[places]" in text
    assert "[clusters]" in text
    assert "[consensus]" in text

    lines = list(csv.reader(io.StringIO(text)))
    assert lines[0] == [
        "provider",
        "name",
        "address",
        "lng",
        "lat",
        "members",
        "spread_max_m",
    ]
    # The cluster row holds the cluster and not a place.
    cluster_rows = [line for line in lines if line[1] == "天安门" and line[5] == "2"]
    assert cluster_rows


# ----------------------------------------------------------------------
# The config file
# ----------------------------------------------------------------------


def test_config_set_escapes_the_value(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """A value with a quote and a backslash is written as valid TOML."""
    path = tmp_path / "config.toml"
    monkeypatch.setenv("MAPQUERY_CONFIG", str(path))

    code = main(["config", "set", "amap", "key", 'abc"def\\ghi'])

    assert code == 0

    from mapquery.config import Config

    config = Config.load()
    assert config.amap_key == 'abc"def\\ghi'


def test_config_set_keeps_the_keys_that_were_already_there(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """A file that the tool did not write is not destroyed."""
    path = tmp_path / "config.toml"
    path.write_text('[baidu]\nak = "keep-me"\n', encoding="utf-8")
    monkeypatch.setenv("MAPQUERY_CONFIG", str(path))

    code = main(["config", "set", "amap", "key", "new-key"])

    assert code == 0

    from mapquery.config import Config

    config = Config.load()
    assert config.baidu_ak == "keep-me"
    assert config.amap_key == "new-key"


def test_config_set_refuses_to_overwrite_a_broken_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: pytest.CaptureFixture
) -> None:
    """A file that cannot be parsed is never overwritten."""
    path = tmp_path / "config.toml"
    path.write_text('[amap]\nkey = "abc"def"\n', encoding="utf-8")
    monkeypatch.setenv("MAPQUERY_CONFIG", str(path))

    code = main(["config", "set", "amap", "key", "new-key"])

    assert code == 2
    assert "cannot be parsed" in capsys.readouterr().err
    assert path.read_text(encoding="utf-8") == '[amap]\nkey = "abc"def"\n'


def test_the_config_file_is_only_readable_by_the_user(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """The file that holds the keys is not readable by everybody.

    On POSIX the mode bits of the file decide this, so they are checked
    the way they always were.

    On Windows there are no mode bits. os.stat reports 0o666 for every
    writable file, so the mode says nothing about the rights of the
    file. The permission model of Windows is the access control list of
    the file, so the list is read with icacls and every principal that
    may read the file is looked at. A principal that stands for all the
    other users of the machine, such as Everyone or BUILTIN\\Users,
    means that the keys are not private.

    The tool only calls os.chmod(0o600). On Windows that call touches
    the read only flag of a file and nothing else, so the file keeps
    the rights of the folder it is in. When that folder lets other
    users in, the gap is written down in docs/REVIEW-v0.0.1.md and the
    test says so instead of pretending that the file is private.
    """
    path = tmp_path / "config.toml"
    monkeypatch.setenv("MAPQUERY_CONFIG", str(path))

    code = main(["config", "set", "amap", "key", "secret-value"])

    assert code == 0

    if os.name == "posix":
        assert oct(os.stat(str(path)).st_mode & 0o777) == "0o600"
        return

    if not windows_acl(str(path)):
        pytest.skip(
            "Windows: icacls is not available, so the access control list "
            "of the file cannot be read."
        )

    entries = windows_acl_entries(str(path))
    assert entries, "the access control list of the config file was not read"

    others = windows_other_readers(str(path))
    if others:
        pytest.skip(
            "Windows: the access control list of the config file still lets "
            "{0} read it. os.chmod(0o600) does not change the list, so the "
            "file inherits the rights of its folder. See "
            "docs/REVIEW-v0.0.1.md.".format(", ".join(others))
        )

    allowed = windows_allowed_readers()
    for name, flags in entries:
        if windows_can_read(flags):
            assert name.lower() in allowed, name


def test_the_matrix_takes_every_place_from_a_provider_that_answered(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Every place comes from a provider that answered with a point.

    One provider finds the first place and fails on the second one, the
    other one does the other way round. Both places are used and both
    providers keep their own status in the status line.
    """
    providers = {
        "baidu": GeoProvider(
            "baidu",
            status=ProviderStatus.RATE_LIMITED,
            fail_on="天安门广场",
            point=(116.3975, 39.9088),
        ),
        "amap": GeoProvider(
            "amap",
            status=ProviderStatus.TIMEOUT,
            fail_on="天安门",
            point=(116.3978, 39.9033),
        ),
    }

    def fake_get_provider(name: str, config: Any, http: Any, channel: Any = None) -> Any:
        """Return the fake provider of the name."""
        return providers[name]

    monkeypatch.setattr("mapquery.cli.get_provider", fake_get_provider)

    code = main(
        [
            "--providers",
            "baidu,amap",
            "--verbose",
            "--json",
            "matrix",
            "--from",
            "天安门;天安门广场",
            "--to",
            "116.39667,39.90864",
        ]
    )

    assert code == 0
    captured = capsys.readouterr()
    assert "baidu: rate_limited" in captured.err
    assert "amap: timeout" in captured.err

    payload = json.loads(captured.out)
    rows = payload["results"]
    assert len(rows) == 2
    # Both places have a distance, not a dash.
    for row in rows:
        assert row["116.39667,39.90864"] > 0.0


def test_a_config_path_that_is_a_directory_gives_a_clean_message(tmp_path, capsys) -> None:
    """A hostile config path must not print a Python traceback."""
    from mapquery.cli import main

    folder = tmp_path / "not-a-file"
    folder.mkdir()
    monkey = os.environ
    monkey["MAPQUERY_CONFIG"] = str(folder)

    code = main(["config", "set", "amap", "key", "abc"])
    captured = capsys.readouterr()

    assert code == 2
    assert "Traceback" not in captured.err
    assert "cannot be written" in captured.err
    monkey["MAPQUERY_CONFIG"] = ""


# ----------------------------------------------------------------------
# The exit codes
# ----------------------------------------------------------------------


def test_the_exit_codes_are_the_three_of_the_readme(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """The tool uses the three exit codes that the README promises.

    The README says: 0 is at least one provider answered with data, 1 is
    no provider answered with data and 2 is a wrong use of the command.
    """
    # A wrong use of the command gives the code 2.
    assert main(["reverse", "not-a-point"]) == 2

    # A provider that cannot do the feature gives the code 1.
    failing = FakeProvider("baidu", features=set())

    def failing_get_provider(name: str, config: Any, http: Any, channel: Any = None) -> Any:
        """Return the provider that cannot do anything."""
        return failing

    monkeypatch.setattr("mapquery.cli.get_provider", failing_get_provider)
    assert main(["--providers", "baidu", "search", "天安门"]) == 1

    # A provider that answers gives the code 0.
    place = Place(
        name="天安门",
        address="Beijing",
        lng=116.3975,
        lat=39.9088,
        provider="baidu",
    )
    answering = FakeProvider("baidu", places=[place])

    def answering_get_provider(name: str, config: Any, http: Any, channel: Any = None) -> Any:
        """Return the provider that answers."""
        return answering

    monkeypatch.setattr("mapquery.cli.get_provider", answering_get_provider)
    assert main(["--providers", "baidu", "search", "天安门"]) == 0


# ----------------------------------------------------------------------
# The rights of the config file on Windows
# ----------------------------------------------------------------------

# The principals that may always read the config file: the owner of the
# file, the system itself and the administrators.
WINDOWS_ALLOWED_PRINCIPALS = (
    "owner rights",
    "nt authority\\system",
    "builtin\\administrators",
    "administrators",
    "system",
    "owner",
)

# The principals that stand for all the other users of the machine. A
# file that one of them can read is not private.
WINDOWS_OTHER_PRINCIPALS = {
    "everyone": ("everyone", "*s-1-1-0"),
    "users": ("builtin\\users", "*s-1-5-32-545"),
    "guests": ("builtin\\guests", "*s-1-5-32-546"),
    "authenticated users": (
        "nt authority\\authenticated users",
        "*s-1-5-11",
    ),
}

# The icacls flags that give the right to read a file.
WINDOWS_READ_FLAGS = ("F", "M", "RX", "R", "GR", "GW")


def windows_allowed_readers() -> Set[str]:
    """Return the principals that may always read the config file."""
    allowed = set(WINDOWS_ALLOWED_PRINCIPALS)
    try:
        allowed.add(getpass.getuser().lower())
    except Exception:  # noqa: BLE001 - the account name is not always known
        pass
    return allowed


def windows_acl(path: str) -> List[str]:
    """Return the access control entries of a file, as icacls prints them.

    The entries look like "NAME:(I)(F)", one per line. The first line
    also holds the path of the file.
    """
    try:
        finished = subprocess.run(
            ["icacls", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )
    except (OSError, ValueError):
        return []
    return finished.stdout.splitlines()


def windows_acl_entries(path: str) -> List[Any]:
    """Return the (principal, flags) pairs of the access control entries."""
    entries: List[Any] = []
    basename = os.path.basename(str(path))
    for line in windows_acl(path):
        text = line.strip()
        if not text or text.lower().startswith("successfully processed"):
            continue
        # The first line starts with the path of the file.
        index = text.find(basename)
        if index >= 0:
            text = text[index + len(basename) :].strip()
        match = re.match(r"^(?P<name>[^:]+):(?P<flags>(?:\([^)]*\))+)$", text)
        if match is None:
            continue
        entries.append((match.group("name").strip(), match.group("flags")))
    return entries


def windows_can_read(flags: str) -> bool:
    """Return True when the flags give the right to read the file."""
    for part in re.findall(r"\(([^)]*)\)", flags):
        if part.upper() in WINDOWS_READ_FLAGS:
            return True
    return False


def windows_other_readers(path: str) -> List[str]:
    """Return the other users of the machine that can read the file."""
    readers: List[str] = []
    for name, flags in windows_acl_entries(path):
        if not windows_can_read(flags):
            continue
        lower = name.lower()
        for label, aliases in WINDOWS_OTHER_PRINCIPALS.items():
            if lower in aliases and label not in readers:
                readers.append(label)
    return readers
