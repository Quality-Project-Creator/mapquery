"""Trace the three map data sources and record the replies as test fixtures.

This script is the reason the direct channel works. It calls the data
routes that the providers' own web pages call and writes what comes back
into tests/fixtures. Run it when a provider changes something.

It is deliberately gentle. The keys it uses are shared with the live
websites of the providers, so the script sleeps between calls.

Usage:
    python tools/trace_sources.py
"""

import pathlib
import re
import time
import urllib.parse
from typing import Tuple

import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)

HERE = pathlib.Path(__file__).resolve().parent
FIXTURES = HERE.parent / "tests" / "fixtures"

# The keys that the providers ship inside their own public page bundles.
# They are shared with the live websites, so they are rate limited.
AMAP_KEY = "2f282f369e388ef01bae260cbc35edce"
TENCENT_KEY = "4VQBZ-ZGO3G-VGSQE-ILN4G-LWFUK-5WB7H"
BAIDU_AK = "8z3RxyDq3sseF20zMZcBxkzhfTdAeSq7"

# The mask that is written instead of a key. The name says which key it
# was, so the fixture stays readable.
MASK = "MASKED-{0}"

# The keys of this script and the mask that hides each of them.
SECRET_KEYS = {
    AMAP_KEY: MASK.format("AMAP-FRONT-END-KEY"),
    TENCENT_KEY: MASK.format("TENCENT-FRONT-END-KEY"),
    BAIDU_AK: MASK.format("BAIDU-FRONT-END-AK"),
}

# The names of the query string parameters that hold a key. A reply that
# echoes the request URL carries the key in one of them.
SECRET_PARAMS = ("key", "ak", "sk", "sig", "signature", "secret", "token")

# The pattern of such a parameter in a reply.
SECRET_PATTERN = re.compile(
    r"(?i)\b({0})=([^&\"'\s<>]+)".format("|".join(SECRET_PARAMS))
)

# The pattern of such a field in a JSON reply.
SECRET_JSON_PATTERN = re.compile(
    r"(?i)(\"({0})\"\s*:\s*\")([^\"]*)(\")".format("|".join(SECRET_PARAMS))
)

# The parameter set that the Amap web page sends. Without platform=JS the
# proxy answers USERKEY_PLAT_NOMATCH.
AMAP_JS = "platform=JS&s=rsv3&logversion=2.0&sdkversion=2.0&appname=mapquery&cetype=unify"

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA})


def quote(text: str) -> str:
    """Return the text, ready to be put in a query string."""
    return urllib.parse.quote(text)


def _mask_param(match: "re.Match[str]") -> str:
    """Return one query string parameter with its value masked."""
    value = match.group(2)
    if value.startswith("MASKED"):
        return match.group(0)
    return "{0}={1}".format(match.group(1), MASK.format("SECRET-KEY"))


def _mask_json_field(match: "re.Match[str]") -> str:
    """Return one JSON field with its value masked."""
    value = match.group(3)
    if value.startswith("MASKED"):
        return match.group(0)
    return "{0}{1}{2}".format(match.group(1), MASK.format("SECRET-KEY"), match.group(4))


def scrub(text: str) -> str:
    """Return the reply without any key.

    A reply can echo the request URL, and the URL holds the key. Every
    key value is replaced by a mask, so a recorded fixture can never hold
    a full key. The known keys are masked by name, and every parameter of
    a query string and every field of a JSON body that holds a key is
    masked as well.
    """
    if not text:
        return text
    for key, mask in SECRET_KEYS.items():
        text = text.replace(key, mask)
    text = SECRET_PATTERN.sub(_mask_param, text)
    return SECRET_JSON_PATTERN.sub(_mask_json_field, text)


def grab(name: str, url: str, referer: str, sleep: float = 2.0) -> Tuple[int, str]:
    """Call one url and save the reply as a fixture.

    The reply is scrubbed before it is written, so the fixture never holds
    a full key.
    """
    time.sleep(sleep)
    try:
        response = SESSION.get(url, headers={"Referer": referer}, timeout=25)
        body = response.text
        code = response.status_code
    except Exception as exc:  # the script must not die on one bad call
        body = "ERROR {0}".format(type(exc).__name__)
        code = 0
    body = scrub(body)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / (name + ".json")).write_text(body, encoding="utf-8")
    print("{0:28s} http={1} len={2:7d} {3}".format(name, code, len(body), body[:60].replace("\n", " ")))
    return code, body


def main() -> None:
    """Call every traced route once and record the replies."""
    baidu = "https://api.map.baidu.com/"
    amap = "https://www.amap.com/_AMapService/v3/"
    tencent = "https://apis.map.qq.com/ws/"
    common = "key={0}&{1}".format(AMAP_KEY, AMAP_JS)

    print("Baidu, web route")
    grab(
        "baidu_search",
        baidu + "?qt=s&wd={0}&c=1&pn=0&rn=10&ie=utf-8&oue=1&from=webmap".format(quote("\u5929\u5b89\u95e8")),
        "https://map.baidu.com/",
    )
    grab(
        "baidu_geocode",
        baidu + "?qt=gc&wd={0}&c=1&ie=utf-8&oue=1&from=webmap".format(quote("\u5929\u5b89\u95e8\u5e7f\u573a")),
        "https://map.baidu.com/",
    )
    grab(
        "baidu_reverse",
        baidu + "?qt=rgc&location=39.915119,116.403963&c=1&ie=utf-8&oue=1&from=webmap",
        "https://map.baidu.com/",
    )
    grab(
        "baidu_suggest",
        "https://map.baidu.com/su?wd={0}&cid=1&type=0&pc_ver=2".format(quote("\u5929\u5b89\u95e8")),
        "https://map.baidu.com/",
    )

    print("\nBaidu, official API with the front-end AK")
    grab(
        "baidu_official_search",
        baidu + "place/v2/search?query={0}&region={1}&scope=2&page_size=3&page_num=0&output=json&ak={2}".format(
            quote("\u5929\u5b89\u95e8"), quote("\u5317\u4eac"), BAIDU_AK
        ),
        "https://map.baidu.com/",
    )
    grab(
        "baidu_official_geocode",
        baidu + "geocoding/v3/?address={0}&city={1}&output=json&ak={2}".format(
            quote("\u5929\u5b89\u95e8\u5e7f\u573a"), quote("\u5317\u4eac"), BAIDU_AK
        ),
        "https://map.baidu.com/",
    )
    grab(
        "baidu_official_reverse",
        baidu + "reverse_geocoding/v3/?location=39.915119,116.403963&output=json&ak=" + BAIDU_AK,
        "https://map.baidu.com/",
    )

    print("\nAmap, web service route")
    grab(
        "amap_geocode",
        amap + "geocode/geo?address={0}&city={1}&{2}".format(
            quote("\u5929\u5b89\u95e8\u5e7f\u573a"), quote("\u5317\u4eac"), common
        ),
        "https://www.amap.com/",
    )
    grab(
        "amap_driving",
        amap + "direction/driving?origin=116.397428,39.908823&destination=116.39667,39.90864&" + common,
        "https://www.amap.com/",
    )
    # The poi routes answer 403 on this route. They are recorded so that the
    # failure path stays tested.
    grab(
        "amap_search",
        amap + "place/text?keywords={0}&city=110000&offset=5&{1}".format(
            quote("\u5929\u5b89\u95e8"), common
        ),
        "https://www.amap.com/",
    )
    grab(
        "amap_reverse",
        amap + "geocode/regeo?location=116.397428,39.908823&" + common,
        "https://www.amap.com/",
    )

    print("\nTencent")
    grab(
        "tencent_suggest",
        tencent + "place/v1/suggestion?keyword={0}&region={1}&key={2}".format(
            quote("\u5929\u5b89\u95e8"), quote("\u5317\u4eac"), TENCENT_KEY
        ),
        "https://map.qq.com/",
    )
    grab(
        "tencent_search",
        tencent + "place/v1/search?keyword={0}&boundary=region({1},0)&page_size=5&key={2}".format(
            quote("\u5929\u5b89\u95e8"), quote("\u5317\u4eac"), TENCENT_KEY
        ),
        "https://map.qq.com/",
        sleep=3.0,
    )
    grab(
        "tencent_geocode",
        tencent + "geocoder/v1/?address={0}&key={1}".format(quote("\u5929\u5b89\u95e8\u5e7f\u573a"), TENCENT_KEY),
        "https://map.qq.com/",
        sleep=3.0,
    )
    grab(
        "tencent_reverse",
        tencent + "geocoder/v1/?location=39.908823,116.39747&get_poi=1&key=" + TENCENT_KEY,
        "https://map.qq.com/",
        sleep=3.0,
    )
    grab(
        "tencent_driving",
        tencent + "direction/v1/driving?from=39.908823,116.39747&to=39.990267,116.314934&key=" + TENCENT_KEY,
        "https://map.qq.com/",
        sleep=3.0,
    )

    print("\nfixtures:", ", ".join(sorted(p.name for p in FIXTURES.glob("*.json"))))


if __name__ == "__main__":
    main()
