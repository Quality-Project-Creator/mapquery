"""Tests for the coordinate transforms."""

from mapquery.coords import (
    CoordSystem,
    bd09_to_gcj02,
    convert,
    gcj02_to_bd09,
    gcj02_to_wgs84,
    haversine_m,
    is_outside_china,
    wgs84_to_gcj02,
)

# A point in Beijing in GCJ-02.
BEIJING = (116.397428, 39.908823)


def test_gcj02_to_wgs84_and_back() -> None:
    """The wgs84 inverse is exact enough to come back to the same point."""
    wgs = gcj02_to_wgs84(*BEIJING)
    back = wgs84_to_gcj02(*wgs)
    assert abs(back[0] - BEIJING[0]) < 1e-6
    assert abs(back[1] - BEIJING[1]) < 1e-6


def test_gcj02_to_bd09_and_back() -> None:
    """The Baidu offset pair is a clean round trip."""
    bd = gcj02_to_bd09(*BEIJING)
    back = bd09_to_gcj02(*bd)
    assert abs(back[0] - BEIJING[0]) < 1e-6
    assert abs(back[1] - BEIJING[1]) < 1e-6


def test_wgs84_to_gcj02_moves_the_point() -> None:
    """A point inside China gets an offset of a few hundred metres."""
    lng, lat = wgs84_to_gcj02(*BEIJING)
    assert 0.001 < abs(lng - BEIJING[0]) < 0.02
    assert 0.0001 < abs(lat - BEIJING[1]) < 0.005


def test_points_outside_china_do_not_move() -> None:
    """Points outside the China box stay exactly the same."""
    outside = [(139.6917, 35.6895), (2.3522, 48.8566), (-74.0060, 40.7128), (151.2093, -33.8688)]
    for lng, lat in outside:
        assert is_outside_china(lng, lat) is True
        assert wgs84_to_gcj02(lng, lat) == (lng, lat)
        assert gcj02_to_wgs84(lng, lat) == (lng, lat)


def test_points_inside_china_are_recognised() -> None:
    """A point in Beijing is inside the China box."""
    assert is_outside_china(*BEIJING) is False


def test_haversine_distance_of_a_known_pair() -> None:
    """Two points near each other in Beijing are about 67.8 metres apart.

    The distance comes from the Amap driving sample. The two points are
    0.000758 degrees of longitude and 0.000183 degrees of latitude
    apart, which is 67.8 metres.
    """
    distance = haversine_m(116.397428, 39.908823, 116.39667, 39.90864)
    assert abs(distance - 67.78) < 1.0


def test_bd09_is_offset_from_gcj02() -> None:
    """The Baidu point sits about 0.0065 degrees east of the GCJ-02 point."""
    bd_lng, bd_lat = gcj02_to_bd09(*BEIJING)
    offset = abs(bd_lng - BEIJING[0])
    assert 0.004 < offset < 0.009
    assert abs(bd_lat - BEIJING[1]) < 0.02


def test_convert_uses_the_same_functions() -> None:
    """The convert helper gives the same answer as the direct calls."""
    converted = convert(*BEIJING, CoordSystem.GCJ02, CoordSystem.BD09)
    assert converted == gcj02_to_bd09(*BEIJING)

    back = convert(*converted, CoordSystem.BD09, CoordSystem.GCJ02)
    assert abs(back[0] - BEIJING[0]) < 1e-6
    assert abs(back[1] - BEIJING[1]) < 1e-6


def test_convert_accepts_plain_text_names() -> None:
    """The system names can be given as text."""
    converted = convert(*BEIJING, "gcj02", "bd09")
    assert converted == gcj02_to_bd09(*BEIJING)


def test_convert_keeps_the_same_system() -> None:
    """Converting a point to its own system changes nothing."""
    assert convert(*BEIJING, CoordSystem.WGS84, CoordSystem.WGS84) == BEIJING
