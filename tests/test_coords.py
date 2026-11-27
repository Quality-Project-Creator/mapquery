"""Tests for the coordinate transforms."""

import pytest

from mapquery.coords import (
    CN_MAX_LAT,
    CN_MAX_LNG,
    CN_MIN_LAT,
    CN_MIN_LNG,
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

# A few points in China in GCJ-02. They cover the north, the south, the
# east, the west and the middle of the country.
CITIES = (
    ("beijing", 116.397428, 39.908823),
    ("shanghai", 121.473701, 31.230416),
    ("shenzhen", 114.057868, 22.543099),
    ("urumqi", 87.617733, 43.792818),
    ("lhasa", 91.132212, 29.660361),
    ("harbin", 126.534967, 45.803775),
    ("sanya", 109.511000, 18.253000),
)

# Every pair of the three systems.
SYSTEM_PAIRS = (
    (CoordSystem.WGS84, CoordSystem.GCJ02),
    (CoordSystem.WGS84, CoordSystem.BD09),
    (CoordSystem.GCJ02, CoordSystem.WGS84),
    (CoordSystem.GCJ02, CoordSystem.BD09),
    (CoordSystem.BD09, CoordSystem.WGS84),
    (CoordSystem.BD09, CoordSystem.GCJ02),
)


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


# ----------------------------------------------------------------------
# The round trip of the transforms
# ----------------------------------------------------------------------


def test_the_wgs84_round_trip_is_exact_in_every_city() -> None:
    """Every point of China comes back to the same place after the pair.

    The wgs84 inverse is solved with three passes, so the error is far
    below one millimetre. A bigger error would mean that the order of
    the pair or the sign of the offset is wrong.
    """
    for name, lng, lat in CITIES:
        forward = wgs84_to_gcj02(lng, lat)
        back = gcj02_to_wgs84(*forward)
        assert haversine_m(back[0], back[1], lng, lat) < 0.01, name


def test_the_bd09_round_trip_is_exact_in_every_city() -> None:
    """The Baidu pair is a clean round trip too."""
    for name, lng, lat in CITIES:
        forward = gcj02_to_bd09(lng, lat)
        back = bd09_to_gcj02(*forward)
        assert haversine_m(back[0], back[1], lng, lat) < 0.2, name


def test_the_whole_chain_comes_back_to_the_same_place() -> None:
    """WGS-84 to BD-09 and back to WGS-84 keeps the place.

    This is the chain that the Baidu provider really uses: the point of
    the user is WGS-84, the answer of Baidu is BD-09 and the answer of
    the tool is GCJ-02 again.
    """
    for name, lng, lat in CITIES:
        bd = convert(lng, lat, CoordSystem.WGS84, CoordSystem.BD09)
        gcj = convert(*bd, CoordSystem.BD09, CoordSystem.GCJ02)
        wgs = convert(*gcj, CoordSystem.GCJ02, CoordSystem.WGS84)
        assert haversine_m(wgs[0], wgs[1], lng, lat) < 0.5, name


def test_every_pair_of_systems_comes_back_to_the_same_place() -> None:
    """Every way of converting a point and back gives the same place."""
    for name, lng, lat in CITIES:
        for source, target in SYSTEM_PAIRS:
            there = convert(lng, lat, source, target)
            back = convert(*there, target, source)
            assert haversine_m(back[0], back[1], lng, lat) < 0.5, (
                name,
                str(source),
                str(target),
            )


# ----------------------------------------------------------------------
# The order of the pair
# ----------------------------------------------------------------------


def test_the_result_keeps_the_order_of_the_pair() -> None:
    """The first number of the result is the longitude.

    A result that holds the latitude first would be a point in the
    wrong place, and the distance to the real place would be thousands
    of kilometres.
    """
    for name, lng, lat in CITIES:
        result = convert(lng, lat, CoordSystem.GCJ02, CoordSystem.BD09)
        assert 70.0 < result[0] < 140.0, name
        assert 0.0 < result[1] < 60.0, name


def test_the_order_of_the_arguments_matters() -> None:
    """The first number of the pair is the longitude.

    The pair (39.908823, 116.397428) is not the gate. It holds the
    latitude of the gate in the first place and its longitude in the
    second one. The Baidu offset is the same for both, so the two
    results differ only in the order of the two numbers.
    """
    straight = convert(*BEIJING, CoordSystem.GCJ02, CoordSystem.BD09)
    swapped = convert(BEIJING[1], BEIJING[0], CoordSystem.GCJ02, CoordSystem.BD09)

    assert straight != swapped

    # The right order keeps a longitude in the first place.
    assert 100.0 < straight[0] < 130.0
    assert 30.0 < straight[1] < 50.0

    # The wrong order puts the latitude of the gate in the first place.
    assert 30.0 < swapped[0] < 50.0
    assert 100.0 < swapped[1] < 130.0


def test_the_order_of_the_pair_is_the_same_in_every_transform() -> None:
    """Every transform takes the longitude first.

    The offset of a point never moves the longitude to the latitude
    band of the country, so a swapped pair is always far away.
    """
    lng, lat = BEIJING
    wrong = (lat, lng)

    assert haversine_m(*wgs84_to_gcj02(lng, lat), lng, lat) < 1000.0
    assert haversine_m(*wgs84_to_gcj02(*wrong), lng, lat) > 1000.0
    assert haversine_m(*gcj02_to_bd09(lng, lat), lng, lat) < 1000.0
    assert haversine_m(*gcj02_to_bd09(*wrong), lng, lat) > 1000.0


# ----------------------------------------------------------------------
# The border of the country
# ----------------------------------------------------------------------


def test_the_edge_of_the_china_box_is_inside() -> None:
    """A point exactly on the border of the box is inside China."""
    assert is_outside_china(CN_MIN_LNG, CN_MIN_LAT) is False
    assert is_outside_china(CN_MAX_LNG, CN_MAX_LAT) is False
    assert is_outside_china(CN_MIN_LNG, CN_MAX_LAT) is False
    assert is_outside_china(CN_MAX_LNG, CN_MIN_LAT) is False


def test_a_point_just_outside_the_china_box_is_outside() -> None:
    """A point just outside the border is outside China."""
    assert is_outside_china(CN_MIN_LNG - 0.001, CN_MIN_LAT) is True
    assert is_outside_china(CN_MAX_LNG + 0.001, CN_MAX_LAT) is True
    assert is_outside_china(CN_MIN_LNG, CN_MIN_LAT - 0.001) is True
    assert is_outside_china(CN_MAX_LNG, CN_MAX_LAT + 0.001) is True


def test_a_point_on_the_border_is_inside_and_moves() -> None:
    """A point exactly on the border is inside, so the offset is applied."""
    lng, lat = CN_MIN_LNG, CN_MIN_LAT

    assert is_outside_china(lng, lat) is False
    assert wgs84_to_gcj02(lng, lat) != (lng, lat)


def test_a_point_just_outside_the_border_does_not_move() -> None:
    """A point just outside the border is outside, so it stays."""
    lng, lat = CN_MIN_LNG - 0.001, CN_MIN_LAT

    assert is_outside_china(lng, lat) is True
    assert wgs84_to_gcj02(lng, lat) == (lng, lat)
    assert gcj02_to_wgs84(lng, lat) == (lng, lat)


def test_a_point_outside_china_does_not_move_in_the_gcj02_pair() -> None:
    """The WGS-84 and GCJ-02 transforms leave a point outside China alone."""
    outside = (139.6917, 35.6895)

    assert convert(*outside, CoordSystem.WGS84, CoordSystem.GCJ02) == outside
    assert convert(*outside, CoordSystem.GCJ02, CoordSystem.WGS84) == outside


def test_the_bd09_offset_is_applied_outside_china_too() -> None:
    """Baidu does not use the China box, so its offset is always applied.

    A point outside China is not a place of Baidu, but the transform
    still shifts it. The round trip still gives the same place back, so
    the tool never loses a point.
    """
    outside = (139.6917, 35.6895)

    bd = convert(*outside, CoordSystem.GCJ02, CoordSystem.BD09)
    assert bd != outside
    assert convert(*bd, CoordSystem.BD09, CoordSystem.GCJ02) == pytest.approx(outside)


def test_the_equator_and_the_prime_meridian_are_outside() -> None:
    """The origin of the map is not in China."""
    assert is_outside_china(0.0, 0.0) is True
    assert wgs84_to_gcj02(0.0, 0.0) == (0.0, 0.0)


# ----------------------------------------------------------------------
# The size of the offsets
# ----------------------------------------------------------------------


def test_the_bd09_offset_is_the_documented_one() -> None:
    """The Baidu offset is about 0.0065 degrees east and north."""
    for name, lng, lat in CITIES:
        bd_lng, bd_lat = gcj02_to_bd09(lng, lat)
        assert 0.0063 < bd_lng - lng < 0.0067, name
        assert 0.0055 < bd_lat - lat < 0.0065, name


def test_the_wgs84_offset_stays_inside_the_country() -> None:
    """The offset of WGS-84 is never more than a few hundred metres."""
    for name, lng, lat in CITIES:
        gcj_lng, gcj_lat = wgs84_to_gcj02(lng, lat)
        assert haversine_m(gcj_lng, gcj_lat, lng, lat) < 1000.0, name
        assert haversine_m(gcj_lng, gcj_lat, lng, lat) > 50.0, name


def test_the_offset_grows_towards_the_middle_of_the_country() -> None:
    """The offset is the biggest in the middle of the country.

    The formula of the offset has the biggest term in the middle of
    China, so a point in the middle moves more than a point at the
    border of the box.
    """
    middle = wgs84_to_gcj02(116.397428, 39.908823)
    edge = wgs84_to_gcj02(CN_MAX_LNG - 0.01, 30.0)

    middle_gap = haversine_m(*middle, 116.397428, 39.908823)
    edge_gap = haversine_m(*edge, CN_MAX_LNG - 0.01, 30.0)

    assert middle_gap > edge_gap


# ----------------------------------------------------------------------
# The distance
# ----------------------------------------------------------------------


def test_the_distance_to_itself_is_zero() -> None:
    """A point is zero metres away from itself."""
    assert haversine_m(*BEIJING, *BEIJING) == 0.0


def test_the_distance_does_not_depend_on_the_order_of_the_points() -> None:
    """The distance is the same in both directions."""
    first = haversine_m(116.397428, 39.908823, 121.473701, 31.230416)
    second = haversine_m(121.473701, 31.230416, 116.397428, 39.908823)

    assert first == second


def test_the_distance_between_two_cities_is_known() -> None:
    """Beijing and Shanghai are about 1068 kilometres apart."""
    distance = haversine_m(116.397428, 39.908823, 121.473701, 31.230416)

    assert abs(distance - 1068153.7) < 5000.0


# ----------------------------------------------------------------------
# The names of the systems
# ----------------------------------------------------------------------


def test_the_system_names_are_the_plain_text() -> None:
    """The name of a system is the text that the user types."""
    assert str(CoordSystem.WGS84) == "wgs84"
    assert str(CoordSystem.GCJ02) == "gcj02"
    assert str(CoordSystem.BD09) == "bd09"


def test_convert_refuses_an_unknown_system() -> None:
    """A system that does not exist is an error."""
    with pytest.raises(ValueError):
        convert(*BEIJING, "wgs84", "mars")


def test_convert_refuses_an_unknown_system_name() -> None:
    """The name of the system is checked too."""
    with pytest.raises(ValueError):
        convert(*BEIJING, "gcj02", "not-a-system")
