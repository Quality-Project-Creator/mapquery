"""Tests for the Baidu Mercator conversion."""

from mapquery.coords import haversine_m
from mapquery.mercator import ll_to_mc, mc_to_ll

# The reference vector of the Baidu tables.
REFERENCE_MC = (12958074.255013367, 3572218.8142307573)
REFERENCE_LL = (116.40309499999992, 30.7029838655178)

# The Mercator value of a live Baidu POI and its known position.
LIVE_MC = (12958170.88, 4825940.97)
LIVE_LL = (116.403963, 39.915119)

# Points in Beijing, Shenzhen, Shanghai, Urumqi and Shenzhen.
ROUND_TRIP_POINTS = [
    (116.403891, 39.914552),
    (113.324520, 23.099994),
    (121.473701, 31.230416),
    (87.616848, 43.825592),
    (114.057868, 22.543099),
]


def test_reference_vector() -> None:
    """The known reference vector gives the known answer."""
    lng, lat = mc_to_ll(REFERENCE_MC[0], REFERENCE_MC[1])
    assert abs(lng - REFERENCE_LL[0]) < 1e-9
    assert abs(lat - REFERENCE_LL[1]) < 1e-9


def test_live_poi_value() -> None:
    """The Mercator value of a live Baidu POI gives the known position."""
    lng, lat = mc_to_ll(LIVE_MC[0], LIVE_MC[1])
    assert abs(lng - LIVE_LL[0]) < 1e-5
    assert abs(lat - LIVE_LL[1]) < 1e-5


def test_round_trip_in_five_cities() -> None:
    """The round trip comes back to the same point, under two centimetres."""
    for lng, lat in ROUND_TRIP_POINTS:
        mercator = ll_to_mc(lng, lat)
        back_lng, back_lat = mc_to_ll(mercator[0], mercator[1])
        assert haversine_m(lng, lat, back_lng, back_lat) < 0.02


def test_negative_values_keep_their_sign() -> None:
    """A point in the south and west keeps its sign."""
    lng, lat = mc_to_ll(-LIVE_MC[0], -LIVE_MC[1])
    assert lng < 0.0
    assert lat < 0.0
    assert abs(abs(lng) - LIVE_LL[0]) < 1e-5
    assert abs(abs(lat) - LIVE_LL[1]) < 1e-5

    south = ll_to_mc(-43.8, -22.9)
    assert south[0] < 0.0
    assert south[1] < 0.0
    back = mc_to_ll(south[0], south[1])
    assert back[0] < 0.0
    assert back[1] < 0.0


def test_the_divisor_is_not_a_polynomial_term() -> None:
    """The last number of a row is only the divisor.

    Using it as an eighth term blows the result up. The round trip proves
    that the seven terms are used.
    """
    mercator = ll_to_mc(116.403891, 39.914552)
    back = mc_to_ll(mercator[0], mercator[1])
    assert abs(back[0] - 116.403891) < 1e-6
    assert abs(back[1] - 39.914552) < 1e-6


def test_the_forward_mercator_says_where_it_is_useful() -> None:
    """The docstring of ll_to_mc says that it is only meant below 75 degrees."""
    from mapquery.mercator import ll_to_mc

    assert "75" in (ll_to_mc.__doc__ or "")
