"""Tests for the comparison of the answers of the providers.

Every test uses hand made places. No test touches the network.
"""

from typing import Dict, List

from mapquery.compare import compare_places, is_same_place, normalise_name
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
