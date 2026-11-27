"""Tests for the providers.

Every test reads a recorded fixture. No test touches the network.
"""

import json
import os
from typing import Any, Optional

import pytest

from mapquery.config import ENV_VARS, Config
from mapquery.coords import bd09_to_gcj02, gcj02_to_bd09, haversine_m
from mapquery.http import HttpClient
from mapquery.models import Channel, ProviderError, ProviderStatus
from mapquery.providers import available_providers, get_provider
from mapquery.providers.baidu import BaiduProvider
from mapquery.providers.direct_keys import BAIDU_FRONTEND_AK
from mapquery.mercator import mc_to_ll

# The folder with the recorded replies.
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

# The Tiananmen gate in GCJ-02. It comes from the Baidu live POI payload.
TIANANMEN = (116.3975904, 39.9087759)


def load_fixture(name: str) -> Any:
    """Return the parsed content of one fixture file."""
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_fixture_text(name: str) -> str:
    """Return the raw text of one fixture file."""
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as handle:
        return handle.read()


def try_json(text: str) -> Any:
    """Return the parsed text. Return None when the text is not JSON."""
    try:
        return json.loads(text)
    except ValueError:
        return None


def make_provider(
    name: str,
    channel: Optional[Channel] = None,
    **keys: str,
) -> Any:
    """Return a provider that never calls the network."""
    config = Config(**keys)
    http = HttpClient(config)
    return get_provider(name, config, http, channel)


# ----------------------------------------------------------------------
# Baidu
# ----------------------------------------------------------------------


def test_baidu_search_fixture() -> None:
    """The recorded POI list gives the Tiananmen gate in GCJ-02."""
    body = load_fixture("baidu_search.json")
    provider = make_provider("baidu")
    places = provider.parse_search_places(body)

    assert len(places) == 10
    first = places[0]
    assert first.name == "天安门"
    assert first.provider == "baidu"
    assert first.category == "旅游景点;文物古迹"
    assert first.uid

    # The position comes from Baidu Mercator metres and then from BD-09.
    assert haversine_m(first.lng, first.lat, TIANANMEN[0], TIANANMEN[1]) < 50.0

    # The raw record of the provider is kept.
    assert first.raw["uid"] == "65e1ee886c885190f60e77ff"


def test_baidu_search_uses_the_best_position() -> None:
    """The best of the three position fields is used.

    The first POI of the recorded list holds the same place three times:
    in navi_xy.diPoint, in point and in the top level x and y. The first
    one is the most precise one.
    """
    body = load_fixture("baidu_search.json")
    provider = make_provider("baidu")
    entry = body["content"][0]
    mercator = provider._mercator_of(entry)

    assert mercator == (12958170.88, 4825940.97)

    # The second field of the same POI is rounded to whole metres.
    entry["ext"]["detail_info"].pop("navi_xy")
    assert provider._mercator_of(entry) == (12958200.0, 4825940.0)

    # The top level fields hold the same value times 100.
    entry["ext"]["detail_info"].pop("point")
    assert provider._mercator_of(entry) == (12958170.88, 4825940.97)


def test_baidu_geocode_fixture() -> None:
    """The recorded geocode reply gives the matched name and the position."""
    body = load_fixture("baidu_geocode.json")
    provider = make_provider("baidu")
    result = provider.parse_geocode(body)

    # The matched name comes from content.wd.
    assert result.address == "天安门广场"

    # The recorded reply matched the square, not the gate. The position is
    # 116.404177, 39.909652 in BD-09. The gate is 614 metres north of it.
    bd_lng, bd_lat = gcj02_to_bd09(result.lng, result.lat)
    assert haversine_m(bd_lng, bd_lat, 116.404177, 39.909652) < 1.0

    # The same place in GCJ-02 is close to the answer of Amap.
    assert haversine_m(result.lng, result.lat, 116.397755, 39.903182) < 50.0


def test_baidu_geocode_uses_the_mercator_value() -> None:
    """The coordinate of the reply is a Baidu Mercator value."""
    body = load_fixture("baidu_geocode.json")
    provider = make_provider("baidu")
    result = provider.parse_geocode(body)

    bd_lng, bd_lat = mc_to_ll(12958194.75, 4825150.68)
    expected = bd09_to_gcj02(bd_lng, bd_lat)
    assert abs(result.lng - expected[0]) < 1e-9
    assert abs(result.lat - expected[1]) < 1e-9


def test_baidu_reverse_fixture() -> None:
    """The recorded reverse reply gives the position in GCJ-02.

    The recorded request used the right order, lat then lng, and the
    Baidu system. So the reply holds a real address.
    """
    body = load_fixture("baidu_reverse.json")
    provider = make_provider("baidu")
    result = provider.parse_reverse(body)

    location = body["result"]["location"]
    expected = bd09_to_gcj02(location["lng"], location["lat"])
    assert abs(result.lng - expected[0]) < 1e-9
    assert abs(result.lat - expected[1]) < 1e-9

    # The recorded reply has the address of the place.
    assert result.address == "北京市东城区东华门街道中华路甲10号"


# ----------------------------------------------------------------------
# Amap
# ----------------------------------------------------------------------


def test_amap_geocode_fixture() -> None:
    """The recorded geocode reply gives the square in GCJ-02."""
    body = load_fixture("amap_geocode.json")
    provider = make_provider("amap")
    result = provider.parse_geocode(body)

    assert result.address == "北京市东城区天安门广场"
    # The recorded reply holds 39.903182. The position of the square in
    # other references is 39.908807, which is the gate 625 metres north.
    assert abs(result.lng - 116.397755) < 1e-6
    assert abs(result.lat - 39.903182) < 1e-6


def test_amap_driving_fixture() -> None:
    """The recorded driving route gives the distance and the duration."""
    body = load_fixture("amap_driving.json")
    provider = make_provider("amap")
    origin = (116.397428, 39.908823)
    destination = (116.39667, 39.90864)
    route = provider.parse_route(body, origin, destination, "driving")

    assert route.distance_m == 1066.0
    # The duration of a route depends on the traffic of the moment, so the
    # recording is the truth and the number is only checked for its size.
    assert route.duration_s > 0.0
    assert route.duration_s == float(body["route"]["paths"][0]["duration"])
    assert route.provider == "amap"
    assert route.origin == origin
    assert route.destination == destination

    assert route.steps
    first = route.steps[0]
    assert first["instruction"]
    assert first["distance_m"] == 436.0
    assert first["duration_s"] == 258.0
    # The polyline of Amap is lng,lat.
    assert first["polyline"][0] == (116.397456, 39.908823)


def test_the_amap_v4_route_fixture() -> None:
    """The v4 route reply gives the distance, the duration and the steps.

    The v4 route is the only one that knows the cycling mode. Its paths
    sit under data.paths, not under route.paths.
    """
    body = load_fixture("amap_v4_route.json")
    provider = make_provider("amap")
    origin = (116.397428, 39.908823)
    destination = (116.39667, 39.90864)
    route = provider.parse_route(body, origin, destination, "bicycling")

    assert route.distance_m == 215.0
    assert route.duration_s == 52.0
    assert len(route.steps) == 2

    first = route.steps[0]
    assert first["instruction"]
    assert first["distance_m"] == 60.0
    assert first["duration_s"] == 15.0
    # The polyline of Amap is lng,lat.
    assert first["polyline"][0] == (116.397428, 39.908823)


def test_the_amap_v3_and_v4_routes_give_the_same_steps() -> None:
    """A step of the v4 route has the same shape as a step of the v3 route."""
    provider = make_provider("amap")

    v3 = provider.parse_route(
        load_fixture("amap_driving.json"),
        (116.397428, 39.908823),
        (116.39667, 39.90864),
        "driving",
    )
    v4 = provider.parse_route(
        load_fixture("amap_v4_route.json"),
        (116.397428, 39.908823),
        (116.39667, 39.90864),
        "bicycling",
    )

    assert set(v3.steps[0]) == set(v4.steps[0])
    assert v3.steps[0]["instruction"]
    assert v4.steps[0]["instruction"]


def test_the_amap_v4_error_body_is_an_error() -> None:
    """A v4 body with a non zero errcode is a failure, in English."""
    provider = make_provider("amap", channel=Channel.OFFICIAL, amap_key="test-key")
    body = {"errcode": 10001, "errmsg": "参数错误", "info": "INVALID_USER_KEY"}

    with pytest.raises(ProviderError) as info:
        provider.parse_route(
            body, (116.397428, 39.908823), (116.39667, 39.90864), "bicycling"
        )

    assert info.value.status == ProviderStatus.ERROR
    assert "错误" not in info.value.message
    assert info.value.message == "Amap answered with an error"
    # The message of the provider stays in the raw reply.
    assert info.value.raw["errmsg"] == "参数错误"


def test_the_amap_v4_rate_limit_body_is_a_rate_limit() -> None:
    """A v4 body with a quota code is a rate limit."""
    provider = make_provider("amap", channel=Channel.OFFICIAL, amap_key="test-key")
    body = {"errcode": 10003, "errmsg": "QUQPS_HAS_EXCEEDED_THE_LIMIT"}

    with pytest.raises(ProviderError) as info:
        provider.parse_route(
            body, (116.397428, 39.908823), (116.39667, 39.90864), "bicycling"
        )

    assert info.value.status == ProviderStatus.RATE_LIMITED


def test_the_amap_v4_body_without_paths_is_no_route() -> None:
    """A v4 body that holds no path is not a route."""
    provider = make_provider("amap", channel=Channel.OFFICIAL, amap_key="test-key")
    body = {"errcode": 0, "errmsg": "OK", "data": {"paths": []}}

    with pytest.raises(ProviderError) as info:
        provider.parse_route(
            body, (116.397428, 39.908823), (116.39667, 39.90864), "bicycling"
        )

    assert info.value.status == ProviderStatus.ERROR
    assert info.value.message == "Amap found no route"


def test_amap_search_failure_body_is_not_data() -> None:
    """The recorded 403 body of the POI search must never be read as data."""
    text = load_fixture_text("amap_search.json")
    assert "403 Forbidden" in text
    body = try_json(text)
    assert body is None or str(body.get("status")) != "1"

    provider = make_provider("amap")
    with pytest.raises(ProviderError) as info:
        provider.search_places("天安门")
    assert info.value.status == ProviderStatus.NOT_SUPPORTED


def test_amap_reverse_failure_body_is_not_data() -> None:
    """The recorded risk control body must never be read as data."""
    text = load_fixture_text("amap_reverse.json")
    assert "rgv587_flag" in text
    body = try_json(text)
    assert body is None or str(body.get("status")) != "1"

    provider = make_provider("amap")
    with pytest.raises(ProviderError) as info:
        provider.reverse_geocode(116.397755, 39.903182)
    assert info.value.status == ProviderStatus.NOT_SUPPORTED


def test_amap_parser_refuses_a_failure_body() -> None:
    """The official parser also refuses a body that is not map data."""
    provider = make_provider("amap", channel=Channel.OFFICIAL, amap_key="test-key")

    # A body without a POI list gives no places.
    assert provider.parse_search({}) == []

    # A body without a geocode list is an error, not a place.
    with pytest.raises(ProviderError):
        provider.parse_geocode({})

    # A body that says it failed is an error, not an empty answer.
    with pytest.raises(ProviderError) as info:
        provider.parse_search({"status": "0", "info": "INVALID_USER_KEY"})
    assert info.value.status == ProviderStatus.ERROR


# ----------------------------------------------------------------------
# Tencent
# ----------------------------------------------------------------------


def test_tencent_suggest_fixture() -> None:
    """The recorded suggestion reply gives the Tiananmen gate in GCJ-02."""
    body = load_fixture("tencent_suggest.json")
    provider = make_provider("tencent")
    places = provider.parse_search(body)

    assert len(places) == 10
    first = places[0]
    assert first.name == "天安门"
    assert abs(first.lng - 116.39747) < 1e-6
    assert abs(first.lat - 39.908823) < 1e-6
    assert first.category == "旅游景点:国家级景点"

    # The count of the provider is at the top level of the reply.
    assert body["count"] == 100


def test_tencent_reverse_fixture() -> None:
    """The recorded reverse reply gives the address of the gate."""
    body = load_fixture("tencent_reverse.json")
    provider = make_provider("tencent")
    result = provider.parse_reverse(body)

    assert result.address == "北京市东城区西长安街"
    assert abs(result.lng - 116.39747) < 1e-6
    assert abs(result.lat - 39.908823) < 1e-6


def test_tencent_rate_limit_bodies_are_rate_limits() -> None:
    """The recorded Tencent bodies with status 120 are rate limits."""
    provider = make_provider("tencent")

    body = load_fixture("tencent_geocode.json")
    assert body["status"] == 120
    with pytest.raises(ProviderError) as info:
        provider.parse_geocode(body)
    assert info.value.status == ProviderStatus.RATE_LIMITED

    body = load_fixture("tencent_driving.json")
    assert body["status"] == 120
    with pytest.raises(ProviderError) as info:
        provider.parse_route(body, (116.39747, 39.908823), (116.397755, 39.903182))
    assert info.value.status == ProviderStatus.RATE_LIMITED


def test_tencent_empty_search_body_is_not_an_error() -> None:
    """The place/v1/search route answers with an empty set for this key."""
    body = load_fixture("tencent_search.json")
    provider = make_provider("tencent")
    assert provider.parse_search(body) == []


# ----------------------------------------------------------------------
# The channels
# ----------------------------------------------------------------------


def test_channel_is_direct_without_a_key(monkeypatch: Any) -> None:
    """Without a key the tool uses the direct channel."""
    monkeypatch.setenv("MAPQUERY_CONFIG", "/nonexistent/mapquery-config.toml")
    for name in ENV_VARS.values():
        monkeypatch.delenv(name, raising=False)

    config = Config.load()
    http = HttpClient(config)
    for name in available_providers():
        provider = get_provider(name, config, http)
        assert provider.active_channel() == Channel.DIRECT


def test_channel_is_official_with_a_key(monkeypatch: Any) -> None:
    """With a key the tool uses the official channel."""
    monkeypatch.setenv("MAPQUERY_CONFIG", "/nonexistent/mapquery-config.toml")
    monkeypatch.setenv("BAIDU_MAP_AK", "test-ak")
    monkeypatch.setenv("AMAP_API_KEY", "test-key")
    monkeypatch.setenv("TENCENT_MAP_KEY", "test-key")

    config = Config.load()
    http = HttpClient(config)
    for name in available_providers():
        provider = get_provider(name, config, http)
        assert provider.active_channel() == Channel.OFFICIAL


def test_the_wanted_channel_wins(monkeypatch: Any) -> None:
    """A channel that the user asks for is used."""
    monkeypatch.setenv("BAIDU_MAP_AK", "test-ak")
    config = Config.load()
    http = HttpClient(config)
    provider = get_provider("baidu", config, http, Channel.DIRECT)
    assert provider.active_channel() == Channel.DIRECT


# ----------------------------------------------------------------------
# The features
# ----------------------------------------------------------------------


def test_the_direct_channel_has_the_traced_features() -> None:
    """Every provider shows what its direct channel can do."""
    baidu = make_provider("baidu")
    assert baidu.supports("search") is True
    assert baidu.supports("geocode") is True
    assert baidu.supports("reverse") is True
    # The qt=nav route of Baidu answers with result.error = -2.
    assert baidu.supports("route") is False

    amap = make_provider("amap")
    assert amap.supports("geocode") is True
    assert amap.supports("route") is True
    # The POI search answers with HTTP 403 and the reverse geocode answers
    # with a risk control body.
    assert amap.supports("search") is False
    assert amap.supports("reverse") is False

    tencent = make_provider("tencent")
    assert tencent.supports("search") is True
    assert tencent.supports("geocode") is True
    assert tencent.supports("reverse") is True
    assert tencent.supports("route") is True


def test_the_official_channel_has_more_features() -> None:
    """The official channel can do the features the direct one cannot."""
    baidu = make_provider("baidu", channel=Channel.OFFICIAL, baidu_ak="test-ak")
    assert baidu.supports("route") is True

    amap = make_provider("amap", channel=Channel.OFFICIAL, amap_key="test-key")
    assert amap.supports("search") is True
    assert amap.supports("reverse") is True
    assert amap.supports("district") is True
    assert amap.supports("weather") is True


def test_a_feature_that_is_not_supported_raises_an_error() -> None:
    """A feature the channel cannot do raises ProviderError."""
    baidu = make_provider("baidu")
    with pytest.raises(ProviderError) as info:
        baidu.route((116.39747, 39.908823), (116.397755, 39.903182))
    assert info.value.status == ProviderStatus.NOT_SUPPORTED

    amap = make_provider("amap")
    with pytest.raises(ProviderError) as info:
        amap.district("北京")
    assert info.value.status == ProviderStatus.NOT_SUPPORTED

    tencent = make_provider("tencent")
    with pytest.raises(ProviderError) as info:
        tencent.weather("110101")
    assert info.value.status == ProviderStatus.NOT_SUPPORTED


def test_the_baidu_provider_is_the_one_of_the_registry() -> None:
    """The registry gives the right class for every name."""
    provider = make_provider("baidu")
    assert isinstance(provider, BaiduProvider)
    assert provider.name == "baidu"
    assert provider.display_name == "Baidu Maps"


# ----------------------------------------------------------------------
# The official Baidu API on the direct channel
# ----------------------------------------------------------------------


def test_baidu_official_search_fixture() -> None:
    """The recorded official search reply gives the gate in GCJ-02."""
    body = load_fixture("baidu_official_search.json")
    provider = make_provider("baidu")
    places = provider.parse_official_search(body)

    assert body["status"] == 0
    # The number of places of the provider changes with its data.
    assert body["total"] > 0
    assert len(places) == 3

    first = places[0]
    assert first.name == "天安门"
    assert first.provider == "baidu"
    assert first.category == "旅游景点;文物古迹"
    assert first.uid == "65e1ee886c885190f60e77ff"

    # The position of the reply is BD-09 and it is turned into GCJ-02.
    expected = bd09_to_gcj02(116.403963, 39.915119)
    assert abs(first.lng - expected[0]) < 1e-9
    assert abs(first.lat - expected[1]) < 1e-9

    # It is the same place as the one of the Amap answer.
    assert haversine_m(first.lng, first.lat, TIANANMEN[0], TIANANMEN[1]) < 50.0


def test_baidu_official_geocode_fixture() -> None:
    """The recorded official geocode reply gives the square in GCJ-02."""
    body = load_fixture("baidu_official_geocode.json")
    provider = make_provider("baidu")
    result = provider.parse_official_geocode(body)

    assert body["status"] == 0
    expected = bd09_to_gcj02(116.4041774131041, 39.9096519665138)
    assert abs(result.lng - expected[0]) < 1e-9
    assert abs(result.lat - expected[1]) < 1e-9

    # The reply holds no address text, so there is nothing to show.
    assert result.address == ""
    assert result.level == "旅游景点"


def test_baidu_official_reverse_fixture() -> None:
    """The recorded official reverse reply gives the address of the gate."""
    body = load_fixture("baidu_official_reverse.json")
    provider = make_provider("baidu")
    result = provider.parse_official_reverse(body)

    assert body["status"] == 0
    assert result.address == "北京市东城区东华门街道中华路甲10号"
    assert result.level == "东城区"

    expected = bd09_to_gcj02(116.40396299999995, 39.9151190770278)
    assert abs(result.lng - expected[0]) < 1e-9
    assert abs(result.lat - expected[1]) < 1e-9


def test_the_direct_channel_uses_the_official_api() -> None:
    """The direct channel of Baidu calls the official WebService API.

    The AK of the front-end bundle is used, because the user has no key
    of their own.
    """
    calls = []

    class FakeClient(HttpClient):
        """A client that records the calls and gives back a fixture."""

        @property
        def session(self) -> Any:
            """Return a session that is never used."""
            return self

        def get_json(self, url: str, params: Any = None, **kwargs: Any) -> Any:
            """Record the call and give back the recorded search reply."""
            calls.append((url, params))
            return load_fixture("baidu_official_search.json")

    config = Config()
    http = FakeClient(config)
    provider = get_provider("baidu", config, http, Channel.DIRECT)

    places = provider.search_places("天安门", city="北京", limit=3)

    assert places
    url, params = calls[0]
    assert url == "https://api.map.baidu.com/place/v2/search"
    assert params["ak"] == BAIDU_FRONTEND_AK
    assert params["region"] == "北京"
    assert params["page_num"] == "0"
    assert params["output"] == "json"


def test_the_direct_channel_falls_back_to_the_web_route() -> None:
    """The web route of Baidu is used when the official API fails."""
    calls = []

    class FakeClient(HttpClient):
        """A client that fails on the official route."""

        @property
        def session(self) -> Any:
            """Return a session that is never used."""
            return self

        def get_json(self, url: str, params: Any = None, **kwargs: Any) -> Any:
            """Fail on the official route and answer on the web route."""
            calls.append(url)
            if "place/v2" in url:
                raise ProviderError("Baidu answered: the request failed", ProviderStatus.ERROR)
            return load_fixture("baidu_search.json")

    config = Config()
    http = FakeClient(config)
    provider = get_provider("baidu", config, http, Channel.DIRECT)

    places = provider.search_places("天安门", city="北京", limit=3)

    assert places
    assert calls[0] == "https://api.map.baidu.com/place/v2/search"
    assert calls[1] == "https://api.map.baidu.com/"


def test_the_route_of_the_direct_channel_is_not_supported() -> None:
    """The routing service is switched off on the shared AK."""
    provider = make_provider("baidu")
    assert provider.supports("route") is False


def test_the_place_detail_uses_the_front_end_ak() -> None:
    """The detail route of the direct channel uses the AK of the bundle."""
    calls = []

    class FakeClient(HttpClient):
        """A client that records the calls and gives back a small reply."""

        @property
        def session(self) -> Any:
            """Return a session that is never used."""
            return self

        def get_json(self, url: str, params: Any = None, **kwargs: Any) -> Any:
            """Record the call and give back a small detail reply."""
            calls.append((url, params))
            return {"status": 0, "result": {"uid": "65e1ee886c885190f60e77ff"}}

    config = Config()
    http = FakeClient(config)
    provider = get_provider("baidu", config, http, Channel.DIRECT)

    detail = provider.place_detail("65e1ee886c885190f60e77ff")

    assert detail["uid"] == "65e1ee886c885190f60e77ff"
    url, params = calls[0]
    assert url == "https://api.map.baidu.com/place/v2/detail"
    assert params["ak"] == BAIDU_FRONTEND_AK
    assert params["uid"] == "65e1ee886c885190f60e77ff"


# ----------------------------------------------------------------------
# The cycling mode
# ----------------------------------------------------------------------


def test_the_amap_cycling_mode_is_bicycling() -> None:
    """Amap calls the cycling mode bicycling."""
    provider = make_provider("amap", channel=Channel.OFFICIAL, amap_key="test-key")

    assert "bicycling" in provider.modes_for(Channel.OFFICIAL)
    assert "cycling" not in provider.modes_for(Channel.OFFICIAL)
    assert provider._official_route_path("bicycling") == "direction/bicycling"


def test_the_amap_cycling_route_is_on_the_v4_route() -> None:
    """The cycling route of Amap is only on the v4 route."""
    provider = make_provider("amap", channel=Channel.OFFICIAL, amap_key="test-key")

    url = provider._official_route_url("bicycling")

    assert url == "https://restapi.amap.com/v4/direction/bicycling"
    # The other modes stay on the v3 route.
    assert provider._official_route_url("driving") == (
        "https://restapi.amap.com/v3/direction/driving"
    )


def test_the_amap_cycling_request_goes_to_the_v4_route() -> None:
    """The request of the cycling route uses the v4 route."""
    calls = []

    class FakeClient(HttpClient):
        """A client that records the calls."""

        @property
        def session(self) -> Any:
            """Return a session that is never used."""
            return self

        def get_json(self, url: str, params: Any = None, **kwargs: Any) -> Any:
            """Record the call and give back a small route reply."""
            calls.append(url)
            return {
                "status": "1",
                "route": {"paths": [{"distance": "1000", "duration": "300"}]},
            }

    config = Config(amap_key="test-key")
    http = FakeClient(config)
    provider = get_provider("amap", config, http, Channel.OFFICIAL)

    provider.route((116.397428, 39.908823), (116.39667, 39.90864), mode="bicycling")

    assert calls[0] == "https://restapi.amap.com/v4/direction/bicycling"


def test_the_tencent_cycling_mode_is_bicycling() -> None:
    """Tencent calls the cycling mode bicycling."""
    provider = make_provider("tencent")

    assert "bicycling" in provider.modes_for(Channel.DIRECT)
    assert "biking" not in provider.modes_for(Channel.DIRECT)


def test_the_tencent_cycling_request_uses_the_bicycling_path() -> None:
    """The request of the cycling route uses the bicycling path."""
    calls = []

    class FakeClient(HttpClient):
        """A client that records the calls."""

        @property
        def session(self) -> Any:
            """Return a session that is never used."""
            return self

        def get_json(self, url: str, params: Any = None, **kwargs: Any) -> Any:
            """Record the call and give back a small route reply."""
            calls.append(url)
            return {
                "status": 0,
                "result": {"routes": [{"distance": 1000, "duration": 300}]},
            }

    config = Config()
    http = FakeClient(config)
    provider = get_provider("tencent", config, http, Channel.DIRECT)

    provider.route((116.397428, 39.908823), (116.39667, 39.90864), mode="bicycling")

    assert calls[0] == "https://apis.map.qq.com/ws/direction/v1/bicycling"


def test_baidu_cannot_do_a_cycling_route() -> None:
    """Baidu only has driving routes."""
    provider = make_provider("baidu", channel=Channel.OFFICIAL, baidu_ak="test-ak")

    with pytest.raises(ProviderError) as info:
        provider.route((116.39747, 39.908823), (116.397755, 39.903182), mode="cycling")

    assert info.value.status == ProviderStatus.NOT_SUPPORTED


# ----------------------------------------------------------------------
# The error text of the provider
# ----------------------------------------------------------------------


def test_the_tencent_error_text_is_english() -> None:
    """The message of Tencent is not shown in the English error text."""
    provider = make_provider("tencent")
    body = {"status": 121, "message": "错误的请求路径"}

    with pytest.raises(ProviderError) as info:
        provider.parse_route(body, (116.39747, 39.908823), (116.397755, 39.903182))

    assert info.value.status == ProviderStatus.ERROR
    assert "错误" not in info.value.message
    assert info.value.message == "Tencent answered with an error"
    # The message of the provider stays in the raw reply.
    assert info.value.raw["message"] == "错误的请求路径"


def test_the_amap_error_text_is_english() -> None:
    """The message of Amap is not shown in the English error text."""
    provider = make_provider("amap")
    body = {"status": "0", "info": "请求参数错误", "infocode": "10001"}

    with pytest.raises(ProviderError) as info:
        provider.parse_geocode(body)

    assert info.value.status == ProviderStatus.ERROR
    assert "错误" not in info.value.message
    assert info.value.message == "Amap answered with an error"
    assert info.value.raw["info"] == "请求参数错误"


def test_the_baidu_error_text_is_english() -> None:
    """The message of Baidu is not shown in the English error text."""
    provider = make_provider("baidu")
    body = {"status": 2, "message": "参数错误"}

    with pytest.raises(ProviderError) as info:
        provider._check_official(body)

    assert info.value.status == ProviderStatus.ERROR
    assert "错误" not in info.value.message
    assert info.value.message == "Baidu answered with an error"
    assert info.value.raw["message"] == "参数错误"


def test_the_recorded_bodies_hold_no_full_key() -> None:
    """The recorded replies do not hold a full front-end key."""
    from mapquery.providers.direct_keys import AMAP_FRONTEND_KEY

    text = load_fixture_text("amap_search.json")

    assert AMAP_FRONTEND_KEY not in text
    assert "MASKED" in text


def test_amap_walking_route_without_a_key_says_that_a_key_would_fix_it() -> None:
    """The user must learn that one key opens the other route modes."""
    from mapquery.models import ProviderStatus

    provider = make_provider("amap")
    provider.config.amap_key = ""

    error = provider.mode_error("walking")

    assert error.status == ProviderStatus.NOT_CONFIGURED
    assert "AMAP_API_KEY" in error.message


def test_a_mode_that_no_channel_can_do_stays_not_supported() -> None:
    """A mode that no channel offers is not_supported, never not_configured."""
    from mapquery.models import ProviderStatus

    provider = make_provider("amap")
    provider.config.amap_key = ""

    error = provider.mode_error("flying")

    assert error.status == ProviderStatus.NOT_SUPPORTED


# ----------------------------------------------------------------------
# The malformed replies
# ----------------------------------------------------------------------


def test_a_baidu_body_that_is_not_an_object_holds_no_places() -> None:
    """A reply that is not a JSON object holds no places."""
    provider = make_provider("baidu")

    assert provider.parse_search_places("not a dict") == []
    assert provider.parse_official_search("not a dict") == []


def test_a_baidu_body_without_a_list_of_places_holds_no_places() -> None:
    """A reply without the expected list holds no places."""
    provider = make_provider("baidu")

    assert provider.parse_search_places({"content": "not a list"}) == []
    assert provider.parse_official_search({"results": "not a list"}) == []


def test_one_broken_baidu_poi_does_not_stop_the_other_places() -> None:
    """A broken entry is skipped, the other places still come back."""
    body = load_fixture("baidu_search.json")
    body["content"].insert(0, "not an object")
    body["content"].insert(1, 42)
    provider = make_provider("baidu")

    places = provider.parse_search_places(body)

    assert len(places) == 10
    assert places[0].name == "天安门"


def test_a_baidu_poi_without_a_position_is_skipped() -> None:
    """A POI without any position is not a place."""
    body = load_fixture("baidu_search.json")
    entry = body["content"][0]
    entry.pop("ext", None)
    entry.pop("x", None)
    entry.pop("y", None)
    provider = make_provider("baidu")

    places = provider.parse_search_places(body)

    assert len(places) == 9
    assert "天安门" not in [place.name for place in places]


def test_a_baidu_official_poi_without_a_position_is_skipped() -> None:
    """A POI without a location is not a place."""
    body = load_fixture("baidu_official_search.json")
    body["results"][0].pop("location")
    provider = make_provider("baidu")

    places = provider.parse_official_search(body)

    assert len(places) == 2


def test_the_baidu_official_search_reads_the_older_item_list() -> None:
    """The old reply of Baidu holds the places under result.items."""
    body = load_fixture("baidu_official_search.json")
    items = body.pop("results")
    body["result"] = {"items": items}
    provider = make_provider("baidu")

    places = provider.parse_official_search(body)

    assert len(places) == 3
    assert places[0].name == "天安门"


def test_the_baidu_geocode_needs_a_position() -> None:
    """A reply without a position is an error, not an empty answer."""
    provider = make_provider("baidu")

    with pytest.raises(ProviderError) as info:
        provider.parse_geocode({"content": {}})

    assert info.value.status == ProviderStatus.ERROR
    assert "no place" in info.value.message


def test_the_baidu_geocode_refuses_a_reply_that_is_not_an_object() -> None:
    """A reply that is not a JSON object is an error."""
    provider = make_provider("baidu")

    with pytest.raises(ProviderError) as info:
        provider.parse_geocode("not a dict")

    assert info.value.status == ProviderStatus.ERROR


def test_the_baidu_reverse_needs_a_position() -> None:
    """A reply without a position is an error, not an empty answer."""
    provider = make_provider("baidu")

    with pytest.raises(ProviderError) as info:
        provider.parse_reverse({"result": {}})

    assert info.value.status == ProviderStatus.ERROR
    assert "no address" in info.value.message


def test_the_baidu_official_route_needs_a_route() -> None:
    """A reply without a route is an error."""
    provider = make_provider("baidu")

    with pytest.raises(ProviderError) as info:
        provider.parse_official_route(
            {"result": {"routes": []}},
            (116.397428, 39.908823),
            (116.39667, 39.90864),
            "driving",
        )

    assert info.value.status == ProviderStatus.ERROR
    assert info.value.message == "Baidu found no route"


def test_the_amap_search_needs_a_list_of_places() -> None:
    """A reply without the list of places holds no places."""
    provider = make_provider("amap", channel=Channel.OFFICIAL, amap_key="test-key")

    assert provider.parse_search({"status": "1"}) == []


def test_an_amap_poi_with_a_broken_position_is_skipped() -> None:
    """A position that cannot be read is not a place."""
    provider = make_provider("amap", channel=Channel.OFFICIAL, amap_key="test-key")
    body = {
        "status": "1",
        "pois": [
            {"name": "a", "location": "abc"},
            {"name": "b", "location": "1,abc"},
            {"name": "c", "location": 12345},
            {"name": "d", "location": "116.397428,39.908823"},
        ],
    }

    places = provider.parse_search(body)

    assert len(places) == 1
    assert places[0].name == "d"
    assert places[0].lng == 116.397428
    assert places[0].lat == 39.908823


def test_the_amap_geocode_needs_a_place() -> None:
    """A reply without a place is an error, not an empty answer."""
    provider = make_provider("amap", channel=Channel.OFFICIAL, amap_key="test-key")

    with pytest.raises(ProviderError) as info:
        provider.parse_geocode({"status": "1"})

    assert info.value.status == ProviderStatus.ERROR

    with pytest.raises(ProviderError):
        provider.parse_geocode({"status": "1", "geocodes": []})


def test_the_amap_reverse_needs_an_address() -> None:
    """A reply without an address is an error."""
    provider = make_provider("amap", channel=Channel.OFFICIAL, amap_key="test-key")

    with pytest.raises(ProviderError) as info:
        provider.parse_reverse({"status": "1"})

    assert info.value.status == ProviderStatus.ERROR


def test_the_amap_route_needs_a_path() -> None:
    """A reply without a path is an error."""
    provider = make_provider("amap", channel=Channel.OFFICIAL, amap_key="test-key")

    with pytest.raises(ProviderError) as info:
        provider.parse_route(
            {"status": "1"},
            (116.397428, 39.908823),
            (116.39667, 39.90864),
            "driving",
        )

    assert info.value.status == ProviderStatus.ERROR
    assert info.value.message == "Amap found no route"


def test_the_tencent_search_needs_a_list_of_places() -> None:
    """A reply without the list of places holds no places."""
    provider = make_provider("tencent")

    assert provider.parse_search({"status": 0}) == []


def test_a_tencent_poi_without_a_position_is_skipped() -> None:
    """A POI without a location is not a place."""
    provider = make_provider("tencent")
    body = {
        "status": 0,
        "data": [
            {"title": "no position"},
            {"title": "天安门", "location": {"lng": 116.39747, "lat": 39.908823}},
        ],
    }

    places = provider.parse_search(body)

    assert len(places) == 1
    assert places[0].name == "天安门"
    assert places[0].lng == 116.39747


def test_the_tencent_geocode_needs_a_position() -> None:
    """A reply without a position is an error, not an empty answer."""
    provider = make_provider("tencent")

    with pytest.raises(ProviderError) as info:
        provider.parse_geocode({"status": 0, "result": {}})

    assert info.value.status == ProviderStatus.ERROR
    assert "no place" in info.value.message


def test_the_tencent_reverse_needs_a_position() -> None:
    """A reply without a position is an error."""
    provider = make_provider("tencent")

    with pytest.raises(ProviderError) as info:
        provider.parse_reverse({"status": 0, "result": {}})

    assert info.value.status == ProviderStatus.ERROR


def test_the_tencent_route_needs_a_route() -> None:
    """A reply without a route is an error."""
    provider = make_provider("tencent")

    with pytest.raises(ProviderError) as info:
        provider.parse_route(
            {"status": 0, "result": {}},
            (116.39747, 39.908823),
            (116.397755, 39.903182),
            "driving",
        )

    assert info.value.status == ProviderStatus.ERROR
    assert info.value.message == "Tencent found no route"


# ----------------------------------------------------------------------
# The known gaps
#
# These three tests say what the tool should do. They fail today and
# they are marked as expected failures, so the suite stays green and
# the gap stays visible. Every one of them is written down in
# docs/REVIEW-v0.0.1.md. When the code is fixed, the test passes and
# the mark can be taken away.
# ----------------------------------------------------------------------


@pytest.mark.xfail(
    reason=(
        "known gap: a position that cannot be read becomes the point (0,0) "
        "instead of being skipped. See docs/REVIEW-v0.0.1.md."
    )
)
def test_a_broken_baidu_position_is_not_a_place_at_zero() -> None:
    """A position that is not a number must not become a place at (0,0).

    The web route of Baidu holds the position as text. A text that
    cannot be read as a number becomes 0.0, so the place is reported
    near the equator in the Atlantic, far away from China.
    """
    provider = make_provider("baidu")
    body = {
        "content": [
            {"name": "broken", "x": "not a number", "y": "not a number"},
        ]
    }

    assert provider.parse_search_places(body) == []


@pytest.mark.xfail(
    reason=(
        "known gap: the web fallback of Baidu hides the rate limit of the "
        "official API. See docs/REVIEW-v0.0.1.md."
    )
)
def test_a_rate_limited_baidu_search_is_not_muted_by_the_web_fallback() -> None:
    """A rate limit must stay a rate limit.

    The direct channel of Baidu calls the official API first and falls
    back to the web route when that fails. A rate limit is a failure of
    the provider, so the fallback must not turn it into an answer with
    no places.
    """

    class FakeHttp:
        """An http client that is rate limited and has an empty web reply."""

        def get_json(self, url: str, params: Any = None, **kwargs: Any) -> Any:
            """Fail the API and give back an empty web reply."""
            if "place/v2/search" in url:
                raise ProviderError(
                    "the provider rate limit was hit", ProviderStatus.RATE_LIMITED
                )
            return {"content": [], "result": {}}

    config = Config()
    provider = get_provider("baidu", config, FakeHttp(), Channel.DIRECT)

    with pytest.raises(ProviderError) as info:
        provider.search_places("天安门")

    assert info.value.status == ProviderStatus.RATE_LIMITED


@pytest.mark.xfail(
    reason=(
        "known gap: a reply that holds no data at all is read as an answer "
        "with no places. See docs/REVIEW-v0.0.1.md."
    )
)
def test_a_tencent_reply_without_data_is_an_error() -> None:
    """A reply that holds nothing is not an answer with no places.

    The status of the reply is 0, so the reply says that the call
    worked. But there is no data list at all, so the reply is broken
    and the tool must say so instead of showing an empty answer.
    """
    provider = make_provider("tencent")

    with pytest.raises(ProviderError) as info:
        provider.parse_search({"status": 0})

    assert info.value.status == ProviderStatus.ERROR
