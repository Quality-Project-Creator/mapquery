"""Comparison of the answers of the providers.

The tool asks every provider the same question. The answers are not the
same. The names are written differently, the positions are a bit apart and
some providers know a place that the others do not know.

This module groups the places that are clearly the same place and it
measures how far the providers are apart.

The rules are simple:

- Two places of different providers are the same place when they are less
  than 150 metres apart and their names look alike. The names are compared
  after a normal form pass, after the spaces are removed and in small
  letters. A name ratio of 0.55 is enough.
- Two places that are less than 25 metres apart are the same place, even
  when the names are different. That is the same building. This rule
  holds for any two places, also for two places of one provider.
"""

import difflib
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from .coords import haversine_m
from .models import Coord, Place

# The largest distance for a match when the names are similar.
MATCH_DISTANCE_M = 150.0

# The smallest name ratio for a match.
MATCH_NAME_RATIO = 0.55

# The distance under which two places are the same building.
SAME_PLACE_DISTANCE_M = 25.0


def normalise_name(name: str) -> str:
    """Return a name in a form that can be compared with another name.

    The name is put in the normal form of Unicode, the spaces are removed
    and the letters are made small.
    """
    text = unicodedata.normalize("NFKC", name or "")
    text = "".join(text.split())
    return text.casefold()


def name_similarity(first: str, second: str) -> float:
    """Return how similar two names are. The value is from 0 to 1."""
    return difflib.SequenceMatcher(None, first, second).ratio()


def distance_between(first: Place, second: Place) -> float:
    """Return the distance between two places in metres."""
    return haversine_m(first.lng, first.lat, second.lng, second.lat)


def is_same_place(
    first: Place,
    second: Place,
    match_distance_m: float = MATCH_DISTANCE_M,
    name_ratio: float = MATCH_NAME_RATIO,
    same_place_distance_m: float = SAME_PLACE_DISTANCE_M,
) -> bool:
    """Return True when two places are the same place.

    They are the same place when they are close and their names look
    alike, or when they are very close. The second rule catches the same
    building under two different names. It holds for any two places, also
    for two places of one provider.

    The three numbers are the settings of the tool. The caller can change
    them, so that only the closest places are matched or that places
    that are further apart are matched too.
    """
    gap = distance_between(first, second)
    if gap <= same_place_distance_m:
        return True
    if gap > match_distance_m:
        return False
    ratio = name_similarity(normalise_name(first.name), normalise_name(second.name))
    return ratio >= name_ratio


class _UnionFind:
    """A small structure that keeps groups of items together."""

    def __init__(self, size: int) -> None:
        """Give every item a group of its own."""
        self._parent: List[int] = list(range(size))

    def find(self, item: int) -> int:
        """Return the group of one item."""
        while self._parent[item] != item:
            self._parent[item] = self._parent[self._parent[item]]
            item = self._parent[item]
        return item

    def union(self, first: int, second: int) -> None:
        """Put two items in the same group."""
        root_first = self.find(first)
        root_second = self.find(second)
        if root_first != root_second:
            self._parent[root_second] = root_first


def _place_dict(place: Place, centre: Optional[Coord]) -> Dict[str, Any]:
    """Return one place as a dict, with the distance from the centre."""
    row: Dict[str, Any] = {
        "provider": place.provider,
        "name": place.name,
        "address": place.address,
        "lng": place.lng,
        "lat": place.lat,
        "category": place.category,
    }
    if centre is not None:
        row["distance_m"] = haversine_m(place.lng, place.lat, centre[0], centre[1])
    return row


def _display_name(members: List[Place]) -> str:
    """Return the name to show for a cluster.

    The most common name wins. When two names are equally common the
    shortest one wins.
    """
    counts: Dict[str, int] = {}
    for member in members:
        key = normalise_name(member.name)
        counts[key] = counts.get(key, 0) + 1

    best_key = ""
    best_count = 0
    for key in counts:
        if counts[key] > best_count:
            best_key = key
            best_count = counts[key]

    candidates = [member for member in members if normalise_name(member.name) == best_key]
    if not candidates:
        return ""
    candidates.sort(key=lambda member: (len(member.name), member.name))
    return candidates[0].name


def _spread_of(members: List[Place]) -> Tuple[float, float]:
    """Return the largest and the mean distance between the members."""
    distances: List[float] = []
    for first in range(len(members)):
        for second in range(first + 1, len(members)):
            distances.append(distance_between(members[first], members[second]))
    if not distances:
        return 0.0, 0.0
    return max(distances), sum(distances) / len(distances)


def compare_places(
    places_by_provider: Dict[str, List[Place]],
    centre: Optional[Coord] = None,
    skipped: Optional[Dict[str, str]] = None,
    match_distance_m: float = MATCH_DISTANCE_M,
    name_ratio: float = MATCH_NAME_RATIO,
    same_place_distance_m: float = SAME_PLACE_DISTANCE_M,
) -> Dict[str, Any]:
    """Compare the places that the providers answered with.

    The input is a dict of provider name to list of places. Only the
    providers whose answer was ok should be in it. The centre is the
    point of the search in GCJ-02 order. It is optional.

    The three numbers are the rules of the match. They have the values
    that the module holds as its own, so the answer of a run without
    settings stays the same as it was.

    The answer holds the clusters, the consensus, the spread, the places
    of every provider and the rules that were used.
    """
    providers = list(places_by_provider.keys())

    entries: List[Tuple[str, Place]] = []
    for provider in providers:
        for place in places_by_provider[provider]:
            entries.append((provider, place))

    groups = _UnionFind(len(entries))
    for first in range(len(entries)):
        for second in range(first + 1, len(entries)):
            first_place = entries[first][1]
            second_place = entries[second][1]
            if (
                distance_between(first_place, second_place) <= same_place_distance_m
            ):
                # The rule of the same building holds for any two places,
                # also for two places of one provider.
                groups.union(first, second)
                continue
            if entries[first][0] == entries[second][0]:
                # Two places of one provider that are further apart are two
                # different places, also when they have the same name.
                continue
            if is_same_place(
                first_place,
                second_place,
                match_distance_m=match_distance_m,
                name_ratio=name_ratio,
                same_place_distance_m=same_place_distance_m,
            ):
                groups.union(first, second)

    # Keep the order of the clusters the same as the order of the answers.
    order: List[int] = []
    buckets: Dict[int, List[int]] = {}
    for index in range(len(entries)):
        root = groups.find(index)
        if root not in buckets:
            buckets[root] = []
            order.append(root)
        buckets[root].append(index)

    clusters: List[Dict[str, Any]] = []
    for number, root in enumerate(order, start=1):
        members = [entries[index][1] for index in buckets[root]]
        member_providers = sorted(set(entries[index][0] for index in buckets[root]))
        spread_max, spread_mean = _spread_of(members)
        lng = sum(member.lng for member in members) / len(members)
        lat = sum(member.lat for member in members) / len(members)
        clusters.append(
            {
                "id": number,
                "name": _display_name(members),
                "providers": member_providers,
                "members": [_place_dict(member, centre) for member in members],
                "centre": {"lng": lng, "lat": lat},
                "spread_max_m": spread_max,
                "spread_mean_m": spread_mean,
            }
        )

    answered = set(providers)
    consensus = [
        cluster for cluster in clusters if set(cluster["providers"]) == answered
    ]

    spreads = [
        cluster["spread_max_m"] for cluster in clusters if len(cluster["members"]) >= 2
    ]
    spread = {
        "count": len(spreads),
        "max_m": max(spreads) if spreads else 0.0,
        "mean_m": (sum(spreads) / len(spreads)) if spreads else 0.0,
    }

    places: Dict[str, List[Dict[str, Any]]] = {}
    for provider in providers:
        places[provider] = [
            _place_dict(place, centre) for place in places_by_provider[provider]
        ]

    return {
        "providers": sorted(answered),
        "places": places,
        "clusters": clusters,
        "consensus": consensus,
        "spread": spread,
        "skipped": dict(skipped) if skipped else {},
        "settings": {
            "match_distance_m": float(match_distance_m),
            "name_ratio": float(name_ratio),
            "same_place_distance_m": float(same_place_distance_m),
        },
    }
