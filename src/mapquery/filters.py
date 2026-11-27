"""The filter on the types of the places.

Every provider uses its own words for the type of a place. Baidu calls a
museum a "科教文化服务", Amap calls it "科教文化服务;博物馆" and Tencent
calls it "科教文化服务:博物馆". A filter that asks every provider for a
type in its own way would ask three different questions and could not be
compared.

The filter of mapquery therefore works on the words that the provider
itself gave:

- a place is kept when one of the wanted words is in its category,
- or when one of the wanted words is in its name.

The rule is the same for every provider, so the answer of one provider
can be put next to the answer of another. The filter never invents a
place and it never changes a place. A place that the provider gave
without a category and without a name is dropped, because there is
nothing to match it on.
"""

from typing import List, Sequence, Tuple

from .models import Place


def parse_types(text: str) -> List[str]:
    """Return the wanted type words.

    The words are separated by commas or by semicolons. An empty entry
    is a mistake of the user, so ValueError is raised and the command
    stops before it calls a provider.
    """
    if text is None:
        return []

    words: List[str] = []
    for part in str(text).replace(";", ",").split(","):
        word = part.strip()
        if not word:
            raise ValueError("the types list has an empty entry")
        words.append(word)
    return words


def normalise(text: str) -> str:
    """Return the text in a form that can be compared with other text.

    The spaces are put in one space each and the letters are made small.
    """
    return " ".join(str(text or "").split()).casefold()


def matches_type(place: Place, words: Sequence[str]) -> bool:
    """Return True when the place is of one of the wanted types.

    An empty list of words matches every place, so a run without a
    filter keeps everything.
    """
    if not words:
        return True

    category = normalise(place.category or "")
    name = normalise(place.name or "")
    for word in words:
        needle = normalise(word)
        if not needle:
            continue
        if needle in category or needle in name:
            return True
    return False


def filter_places(
    places: Sequence[Place],
    words: Sequence[str],
) -> Tuple[List[Place], int, int]:
    """Return the places of one provider that are of the wanted types.

    The second number is the count of the dropped places. The third is
    the count of the dropped places that had no category and no name, so
    that the caller can say that they were dropped without a reason.
    """
    if not words:
        return list(places), 0, 0

    kept: List[Place] = []
    dropped = 0
    without = 0
    for place in places:
        if matches_type(place, words):
            kept.append(place)
            continue
        dropped += 1
        if not normalise(place.category) and not normalise(place.name):
            without += 1

    return kept, dropped, without
