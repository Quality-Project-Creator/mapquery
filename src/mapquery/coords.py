"""Coordinate transforms between WGS-84, GCJ-02 and BD-09.

The tool keeps one internal order and one internal system:
order is (lng, lat) and system is GCJ-02.

Each function is pure. There is no I/O and no network call.
"""

import math
from enum import Enum
from typing import Tuple

# WGS-84 ellipsoid parameters used by the GCJ-02 offset algorithm.
A = 6378245.0
EE = 0.00669342162296594323

# Mean earth radius in metres. Used by the distance function.
EARTH_RADIUS_M = 6371008.8

# The China bounding box used by the offset algorithm.
CN_MIN_LNG = 72.004
CN_MAX_LNG = 137.8347
CN_MIN_LAT = 0.8293
CN_MAX_LAT = 55.8271

# A longitude and latitude pair. Longitude comes first.
Coord = Tuple[float, float]


class CoordSystem(str, Enum):
    """The three coordinate systems that the providers use."""

    WGS84 = "wgs84"
    GCJ02 = "gcj02"
    BD09 = "bd09"

    def __str__(self) -> str:
        """Return the plain text name, such as "gcj02"."""
        return self.value


def is_outside_china(lng: float, lat: float) -> bool:
    """Return True when the point is outside the China bounding box."""
    if lng < CN_MIN_LNG or lng > CN_MAX_LNG:
        return True
    if lat < CN_MIN_LAT or lat > CN_MAX_LAT:
        return True
    return False


def _transform_lat(x: float, y: float) -> float:
    """Return the latitude part of the GCJ-02 offset.

    This is the full reference form. A truncated variant exists that drops
    the sine terms. It drifts 170 to 330 m from the reference form, which is
    far too much for a tool that compares providers, so the full form is used
    on purpose.
    """
    ret = (
        -100.0
        + 2.0 * x
        + 3.0 * y
        + 0.2 * y * y
        + 0.1 * x * y
        + 0.2 * math.sqrt(abs(x))
    )
    ret += (
        20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)
    ) * 2.0 / 3.0
    ret += (
        20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)
    ) * 2.0 / 3.0
    ret += (
        160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)
    ) * 2.0 / 3.0
    return ret


def _transform_lng(x: float, y: float) -> float:
    """Return the longitude part of the GCJ-02 offset.

    This is the full reference form. The truncated variant drops the sine
    terms and drifts 170 to 330 m, so the full form is used on purpose.
    """
    ret = (
        300.0
        + x
        + 2.0 * y
        + 0.1 * x * x
        + 0.1 * x * y
        + 0.1 * math.sqrt(abs(x))
    )
    ret += (
        20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)
    ) * 2.0 / 3.0
    ret += (
        20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)
    ) * 2.0 / 3.0
    ret += (
        150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)
    ) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lng: float, lat: float) -> Coord:
    """Convert WGS-84 to GCJ-02. Points outside China stay unchanged."""
    if is_outside_china(lng, lat):
        return (lng, lat)

    d_lat = _transform_lat(lng - 105.0, lat - 35.0)
    d_lng = _transform_lng(lng - 105.0, lat - 35.0)

    rad_lat = lat / 180.0 * math.pi
    magic = math.sin(rad_lat)
    magic = 1 - EE * magic * magic
    sqrt_magic = math.sqrt(magic)

    d_lat = (d_lat * 180.0) / ((A * (1 - EE)) / (magic * sqrt_magic) * math.pi)
    d_lng = (d_lng * 180.0) / (A / sqrt_magic * math.cos(rad_lat) * math.pi)

    return (lng + d_lng, lat + d_lat)


def gcj02_to_wgs84(lng: float, lat: float) -> Coord:
    """Convert GCJ-02 to WGS-84.

    The inverse is solved by iterative refinement. Three passes give an
    error far below one metre.
    """
    if is_outside_china(lng, lat):
        return (lng, lat)

    guess_lng = lng
    guess_lat = lat
    for _ in range(3):
        shifted_lng, shifted_lat = wgs84_to_gcj02(guess_lng, guess_lat)
        guess_lng += lng - shifted_lng
        guess_lat += lat - shifted_lat

    return (guess_lng, guess_lat)


def gcj02_to_bd09(lng: float, lat: float) -> Coord:
    """Convert GCJ-02 to BD-09, the Baidu system."""
    x = lng
    y = lat
    z = math.sqrt(x * x + y * y) + 0.00002 * math.sin(y * math.pi * 3000.0 / 180.0)
    theta = math.atan2(y, x) + 0.000003 * math.cos(x * math.pi * 3000.0 / 180.0)
    bd_lng = z * math.cos(theta) + 0.0065
    bd_lat = z * math.sin(theta) + 0.006
    return (bd_lng, bd_lat)


def bd09_to_gcj02(lng: float, lat: float) -> Coord:
    """Convert BD-09 to GCJ-02."""
    x = lng - 0.0065
    y = lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * math.pi * 3000.0 / 180.0)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * math.pi * 3000.0 / 180.0)
    gcj_lng = z * math.cos(theta)
    gcj_lat = z * math.sin(theta)
    return (gcj_lng, gcj_lat)


def convert(lng: float, lat: float, from_system: CoordSystem, to_system: CoordSystem) -> Coord:
    """Convert a point from one coordinate system to another.

    Both systems can be a CoordSystem member or its text value.
    """
    source = CoordSystem(from_system)
    target = CoordSystem(to_system)

    if source == target:
        return (lng, lat)

    if source == CoordSystem.WGS84 and target == CoordSystem.GCJ02:
        return wgs84_to_gcj02(lng, lat)
    if source == CoordSystem.GCJ02 and target == CoordSystem.WGS84:
        return gcj02_to_wgs84(lng, lat)
    if source == CoordSystem.GCJ02 and target == CoordSystem.BD09:
        return gcj02_to_bd09(lng, lat)
    if source == CoordSystem.BD09 and target == CoordSystem.GCJ02:
        return bd09_to_gcj02(lng, lat)
    if source == CoordSystem.WGS84 and target == CoordSystem.BD09:
        return gcj02_to_bd09(*wgs84_to_gcj02(lng, lat))
    if source == CoordSystem.BD09 and target == CoordSystem.WGS84:
        return gcj02_to_wgs84(*bd09_to_gcj02(lng, lat))

    raise ValueError("unsupported coordinate conversion: {0} to {1}".format(source, target))


def haversine_m(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    """Return the great circle distance between two points in metres."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = phi2 - phi1
    delta_lambda = math.radians(lng2 - lng1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_M * c
