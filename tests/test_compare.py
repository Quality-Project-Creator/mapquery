"""Tests for the comparison of the answers of the providers.

Every test uses hand made places. No test touches the network.
"""

from typing import Dict, List

import pytest

from mapquery.compare import (
    MATCH_DISTANCE_M,
    MATCH_NAME_RATIO,
    SAME_PLACE_DISTANCE_M,
    compare_places,
    is_same_place,
    normalise_name,
)
from mapquery.filters import filter_places, matches_type, parse_types
from mapquery.models import Place


def make_place(name: str, lng: float, lat: float, provider: str) -> Place:
    """Return one place for the tests."""
    return Place(
        name=name,
        address="somewhere in Beijing",
        lng=lng,
        lat=lat,
        provider=provider,
    )


def make_typed_place(
    name: str,
    category: str,
    lng: float,
    lat: float,
    provider: str,
) -> Place:
    """Return one place that has a category, for the tests."""
    place = make_place(name, lng, lat, provider)
    place.category = category
    return place


def test_names_are_normalised() -> None:
    """The normal form, the spaces and the case are taken away."""
    assert normalise_name("  Tiananmen  Square ") == "tiananmensquare"
    assert normalise_name("ＴＥＮ") == "ten"
    assert normalise_name("天安门 广场") == "天安门广场"


def test_the_same_place_is_recognised() -> None:
    """A close place with a similar name is the same place."""
    first = make_place("天安门", 116.3975, 39.9088, "baidu")
    second = make_place("天安门", 116.3977, 39.9090, "amap")

    assert is_same_place(first, second) is True


def test_a_far_place_is_not_the_same_place() -> None:
    """A place that is far away is never the same place."""
    first = make_place("天安门", 116.3975, 39.9088, "baidu")
    second = make_place("天安门", 116.4010, 39.9088, "amap")

    assert is_same_place(first, second) is False


def test_three_providers_with_one_place_make_one_cluster() -> None:
    """Three providers that find the same place make one cluster."""
    places: Dict[str, List[Place]] = {
        "baidu": [make_place("天安门", 116.3975, 39.9088, "baidu")],
        "amap": [make_place("天安门", 116.3977, 39.9090, "amap")],
        "tencent": [make_place("天安门", 116.3979, 39.9085, "tencent")],
    }

    result = compare_places(places)

    assert len(result["clusters"]) == 1
    cluster = result["clusters"][0]
    assert cluster["providers"] == ["amap", "baidu", "tencent"]
    assert len(cluster["members"]) == 3
    assert cluster["name"] == "天安门"
    assert cluster["spread_max_m"] < 60.0

    # The cluster holds every provider, so it is part of the consensus.
    assert len(result["consensus"]) == 1
    assert result["consensus"][0]["id"] == cluster["id"]

    assert result["spread"]["count"] == 1
    assert result["spread"]["max_m"] < 60.0


def test_three_different_places_make_three_clusters() -> None:
    """Three providers that find three different places do not agree."""
    places: Dict[str, List[Place]] = {
        "baidu": [make_place("天安门", 116.3975, 39.9088, "baidu")],
        "amap": [make_place("王府井", 116.4010, 39.9088, "amap")],
        "tencent": [make_place("故宫", 116.4045, 39.9088, "tencent")],
    }

    result = compare_places(places)

    assert len(result["clusters"]) == 3
    assert result["consensus"] == []
    assert result["spread"]["count"] == 0


def test_a_place_that_comes_twice_stays_in_one_cluster() -> None:
    """One provider that gives the same place twice gives one cluster."""
    first = make_place("天安门", 116.3975, 39.9088, "baidu")
    second = make_place("天安门", 116.3975, 39.9088, "baidu")

    places: Dict[str, List[Place]] = {"baidu": [first, second]}
    result = compare_places(places)

    assert len(result["clusters"]) == 1
    assert len(result["clusters"][0]["members"]) == 2


def test_a_duplicate_joins_the_cluster_of_the_other_providers() -> None:
    """A duplicate of one provider joins the cluster of the others."""
    places: Dict[str, List[Place]] = {
        "baidu": [
            make_place("天安门", 116.3975, 39.9088, "baidu"),
            make_place("天安门", 116.3975, 39.9088, "baidu"),
        ],
        "amap": [make_place("天安门", 116.3977, 39.9090, "amap")],
        "tencent": [make_place("天安门", 116.3979, 39.9085, "tencent")],
    }

    result = compare_places(places)

    assert len(result["clusters"]) == 1
    assert len(result["clusters"][0]["members"]) == 4
    assert result["clusters"][0]["providers"] == ["amap", "baidu", "tencent"]
    assert len(result["consensus"]) == 1


def test_the_consensus_only_counts_the_providers_that_answered() -> None:
    """A provider that did not answer is not part of the consensus."""
    places: Dict[str, List[Place]] = {
        "baidu": [make_place("天安门", 116.3975, 39.9088, "baidu")],
        "tencent": [make_place("天安门", 116.3977, 39.9090, "tencent")],
    }

    result = compare_places(places, skipped={"amap": "no AMAP_API_KEY"})

    assert len(result["consensus"]) == 1
    assert result["consensus"][0]["providers"] == ["baidu", "tencent"]
    assert result["skipped"] == {"amap": "no AMAP_API_KEY"}


def test_the_centre_of_a_cluster_is_the_mean_of_its_members() -> None:
    """The centre of a cluster is the mean of the places in it."""
    places: Dict[str, List[Place]] = {
        "baidu": [make_place("天安门", 116.3970, 39.9080, "baidu")],
        "amap": [make_place("天安门", 116.3978, 39.9084, "amap")],
    }

    result = compare_places(places)
    centre = result["clusters"][0]["centre"]

    assert abs(centre["lng"] - 116.3974) < 1e-9
    assert abs(centre["lat"] - 39.9082) < 1e-9


def test_the_distance_from_the_centre_is_given() -> None:
    """Every place gets the distance from the centre of the search."""
    places: Dict[str, List[Place]] = {
        "baidu": [make_place("天安门", 116.3975, 39.9088, "baidu")],
    }

    result = compare_places(places, centre=(116.3975, 39.9088))

    assert result["places"]["baidu"][0]["distance_m"] < 1.0


def test_two_places_of_one_provider_that_are_close_are_the_same_place() -> None:
    """The 25 metre rule holds for two places of one provider too.

    Two places of one provider that are 25 metres apart are the same
    place, also when their names are different.
    """
    first = make_place("天安门", 116.3975, 39.9088, "baidu")
    # About two metres north of the first place.
    second = make_place("天安门东门", 116.39752, 39.90881, "baidu")

    assert is_same_place(first, second) is True

    places: Dict[str, List[Place]] = {"baidu": [first, second]}
    result = compare_places(places)

    assert len(result["clusters"]) == 1
    assert len(result["clusters"][0]["members"]) == 2


def test_two_places_of_one_provider_that_are_far_are_not_the_same_place() -> None:
    """The 25 metre rule does not join two places that are far away."""
    first = make_place("天安门", 116.3975, 39.9088, "baidu")
    second = make_place("王府井", 116.4010, 39.9088, "baidu")

    assert is_same_place(first, second) is False

    places: Dict[str, List[Place]] = {"baidu": [first, second]}
    result = compare_places(places)

    assert len(result["clusters"]) == 2


# ----------------------------------------------------------------------
# The rules of the match can be changed
# ----------------------------------------------------------------------


def test_a_bigger_cluster_radius_matches_further_places() -> None:
    """A place that is too far away is one place with a bigger radius."""
    first = make_place("天安门", 116.3975, 39.9088, "baidu")
    # About 256 metres to the east.
    second = make_place("天安门", 116.4005, 39.9088, "amap")

    assert is_same_place(first, second) is False

    places: Dict[str, List[Place]] = {"baidu": [first], "amap": [second]}
    result = compare_places(places, match_distance_m=300.0)

    assert len(result["clusters"]) == 1
    assert result["clusters"][0]["providers"] == ["amap", "baidu"]


def test_the_name_ratio_can_be_changed() -> None:
    """Two names that are not alike enough are alike with a lower ratio."""
    first = make_place("北京市东城区天安门广场", 116.3975, 39.9088, "baidu")
    # About 94 metres to the east.
    second = make_place("天安门", 116.3986, 39.9088, "amap")

    assert is_same_place(first, second) is False
    assert is_same_place(first, second, name_ratio=0.4) is True


def test_the_same_place_radius_can_be_changed() -> None:
    """Two places of one provider that are close are one place.

    The names are not alike, so only the rule of the same building can
    join them.
    """
    first = make_place("天安门", 116.3975, 39.9088, "baidu")
    # About two metres north of the first place, with another name.
    second = make_place("西单商场", 116.39752, 39.90881, "baidu")

    assert is_same_place(first, second) is True
    assert is_same_place(first, second, same_place_distance_m=1.0) is False


def test_the_answer_says_which_rules_were_used() -> None:
    """The answer holds the rules that were used."""
    result = compare_places(
        {"baidu": []},
        match_distance_m=250.0,
        name_ratio=0.4,
        same_place_distance_m=10.0,
    )

    assert result["settings"]["match_distance_m"] == 250.0
    assert result["settings"]["name_ratio"] == 0.4
    assert result["settings"]["same_place_distance_m"] == 10.0


def test_the_default_rules_are_the_ones_of_the_module() -> None:
    """A run without settings uses the rules of the module."""
    result = compare_places({"baidu": []})

    assert result["settings"]["match_distance_m"] == MATCH_DISTANCE_M
    assert result["settings"]["name_ratio"] == MATCH_NAME_RATIO
    assert result["settings"]["same_place_distance_m"] == SAME_PLACE_DISTANCE_M


# ----------------------------------------------------------------------
# The filter on the types of the places
# ----------------------------------------------------------------------


def test_the_type_words_are_read_from_a_list() -> None:
    """The words are separated by commas or by semicolons."""
    assert parse_types("景点,博物馆") == ["景点", "博物馆"]
    assert parse_types("景点; 博物馆") == ["景点", "博物馆"]


def test_an_empty_word_in_the_type_list_is_a_mistake() -> None:
    """An empty entry is refused."""
    with pytest.raises(ValueError):
        parse_types("景点,,博物馆")


def test_the_category_of_a_place_decides_its_type() -> None:
    """A place of a wanted type is kept."""
    museum = make_typed_place(
        "故宫博物院", "科教文化服务:博物馆", 116.3975, 39.9088, "tencent"
    )
    park = make_typed_place(
        "天安门", "风景名胜", 116.3975, 39.9088, "tencent"
    )

    assert matches_type(museum, ["博物馆"]) is True
    assert matches_type(park, ["博物馆"]) is False

    kept, dropped, without = filter_places([museum, park], ["博物馆"])

    assert [place.name for place in kept] == ["故宫博物院"]
    assert dropped == 1
    assert without == 0


def test_the_name_of_a_place_is_matched_too() -> None:
    """The word is also looked for in the name of the place."""
    place = make_typed_place(
        "北京动物园", "风景名胜", 116.3975, 39.9088, "tencent"
    )

    assert matches_type(place, ["动物园"]) is True


def test_a_place_without_a_category_and_without_a_name_is_dropped() -> None:
    """There is nothing to match such a place on, so it is dropped."""
    empty = Place(
        name="",
        address="",
        lng=116.3975,
        lat=39.9088,
        provider="baidu",
    )

    kept, dropped, without = filter_places([empty], ["景点"])

    assert kept == []
    assert dropped == 1
    assert without == 1


def test_the_filter_without_words_keeps_every_place() -> None:
    """A run without a filter keeps everything."""
    place = make_place("天安门", 116.3975, 39.9088, "baidu")

    kept, dropped, without = filter_places([place], [])

    assert len(kept) == 1
    assert dropped == 0
    assert without == 0
