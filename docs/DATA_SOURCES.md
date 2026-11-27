# Tracked data sources

How each provider's data route was found, what the request looks like, and what came back.
Every sample here was fetched from the live service and saved as a test fixture under
`tests/fixtures/`. The only exception is the v4 route of Amap, which is written by hand from the
documented shape.

Date of trace: 2026-11-22. All three hosts answered from a plain sandbox with no login.

Re-test: 2026-11-27. The same routes were called once more, one endpoint at a time, with the
sleep of the script kept. The results are in [the re-test section](#re-test-on-2026-11-27).

---

## Why trace at all

The documented WebService APIs all need a key. The front-ends of the three map sites call their
own backends with keys that are shipped inside public JavaScript bundles. Following those calls
gives a working data route with no account and no signup.

This tool therefore has two channels per provider:

- **direct** — the traced front-end route. Default. No key needed.
- **official** — the documented WebService API. Used when the user sets their own key.

---

## Re-test on 2026-11-27

Every route below was called once more on 2026-11-27, one endpoint at a time, with the sleep of
`tools/trace_sources.py` kept. The script was run from a copy outside the repository, so the
recorded fixtures in `tests/fixtures/` were not overwritten; their hashes are the same before and
after the run. The copy only added the printing of the response headers, so that the quota of
every reply is on the record.

### What the tool itself sees

| Provider | Command | Status | Quota headers |
|---|---|---|---|
| Baidu | `mapq search 天安门 --city 北京 --limit 2 --providers baidu` | `ok (direct, 1097 ms)`, 1 attempt | none |
| Amap | `mapq geocode 天安门广场 --city 北京 --providers amap` | `ok (direct, 709 ms)`, 1 attempt | none |
| Amap | `mapq search 天安门 --city 北京 --limit 2 --providers amap` | `not_configured (no AMAP_API_KEY)`, 0 attempts, no request was made | none |
| Tencent | `mapq search 天安门 --city 北京 --limit 2 --providers tencent` | `ok (direct, 1005 ms)`, 1 attempt | `current_qps=1; limit_qps=150; current_pv=368261; limit_pv=20000000000398` |

### The short version

| Provider | Endpoint | HTTP | Quota | Result |
|---|---|---|---|---|
| Baidu | `qt=s` (search) | 200 | none | data, about 280 KB |
| Baidu | `qt=gc` (geocode) | 200 | none | data |
| Baidu | `qt=rgc` (reverse) | 200 | none | data |
| Baidu | `map.baidu.com/su` (suggest) | 200 | none | data |
| Baidu | `place/v2/search` (front-end AK) | 200 | none | `status 0`, `total 106` |
| Baidu | `geocoding/v3` (front-end AK) | 200 | none | `status 0` |
| Baidu | `reverse_geocoding/v3` (front-end AK) | 200 | none | `status 0` |
| Amap | `geocode/geo` | 200 | none | `status 1`, `infocode 10000` |
| Amap | `direction/driving` | 200 | none | `status 1`, `infocode 10000` |
| Amap | `place/text` | **403** | none | HTML error page, not JSON |
| Amap | `geocode/regeo` | 200 | none | HTML risk-control page, not map data |
| Tencent | `place/v1/suggestion` | 200 | `current_qps=1; limit_qps=150` | `status 0` |
| Tencent | `place/v1/search` | 200 | `current_qps=1; limit_qps=300` | `status 0`, `count 0`, `data []` |
| Tencent | `geocoder/v1` (address) | 200 | `current_qps=1; limit_qps=0` | **`status 120`, rate limited** |
| Tencent | `geocoder/v1` (reverse) | 200 | `current_qps=1; limit_qps=500` | `status 0` |
| Tencent | `direction/v1/driving` | 200 | `current_qps=1; limit_qps=0` | **`status 120`, rate limited** |

Nothing changed since the first trace on 2026-11-22. Amap still answers 403 on the POI routes,
the reverse geocode of Amap still answers with a risk-control page, the search of Tencent still
comes back empty for this key, and the geocode and the driving route of Tencent are still rate
limited under load.

---

## Baidu Maps

### How the route was found

`https://map.baidu.com/` calls `https://api.map.baidu.com/?qt=<command>&...`. The `qt` value
selects the operation. No credential is sent.

### Endpoints

| Purpose | Request |
|---|---|
| POI search | `https://api.map.baidu.com/?qt=s&wd={kw}&c={city}&pn=0&rn=10&ie=utf-8&oue=1&from=webmap` |
| Geocode | `https://api.map.baidu.com/?qt=gc&wd={address}&c={city}&ie=utf-8&oue=1&from=webmap` |
| Reverse geocode | `https://api.map.baidu.com/?qt=rgc&location={lat,lng}&c={city}&ie=utf-8&oue=1&from=webmap` |
| Suggest | `https://map.baidu.com/su?wd={kw}&cid=1&type=0&pc_ver=2` |

The city code for a Chinese city is the second half of the value `131` for Beijing.
`qt=gc` returns the city code for an address, which is what makes `qt=s` usable in the first
place.

### The better route: the official API with the front-end AK

Baidu's own page bundle (`init-pkg_*.js`) carries an AK. One of them, `8z3Rxy...` (the full value is in `src/mapquery/providers/direct_keys.py`),
is accepted by the documented WebService API:

| Endpoint | Result with the front-end AK |
|---|---|
| `place/v2/search` | **works** — `total: 106`, first row 天安门 at `39.915119, 116.403963` |
| `geocoding/v3` | **works** |
| `reverse_geocoding/v3` | **works** — 北京市东城区东华门街道中华路甲10号 |
| `place/v2/detail` | **works** |
| `direction/v2/driving` | `status 240` — the driving service is disabled on this app |
| `direction/v2/transit` | `status 240` — same |
| `distance/v1/matrix` | returns an HTML page, the v1 endpoint is retired |

So the direct channel uses the official API, and only routing is missing.
A user's own AK has the routing service enabled, so the official channel covers it.

That first search result is worth a second look: `39.915119, 116.403963` is digit for digit the
position this trace derived on its own from Baidu's web payload and the Mercator inverse. Two
independent routes to the same number.

### Samples

`qt=gc` for 天安门广场 returns the city code and the matched place:

```json
{"result":{"type":35,"qid":"2148480098","qt":"gc","wd":"天安门广场","c":"1","error":0},
 "content":{"cn":"","sc":0,"catalog":"北京市-东城区-天安门广场"}}
```

`su` returns a compact pipe-separated list:

```json
{"q":"天安门","p":false,"t":0,
 "s":["北京市$东城区$$天安门$131$65e1ee036c885190f60e77ff$",
      "北京市$东城区$$天安门广场$131$c9b5fb91d49345bc5d0d0262$"]}
```

### Notes

- `qt=s` is a large reply (about 280 KB) because it carries the full map-side payload. Only the
  `content` array holds the POI list; the rest must be ignored.
- Coordinates in the reply are **BD-09 in Mercator metres**, not lat/lng. See the section
  "The Baidu Mercator problem" below.
- The old `v1` WebService endpoints are retired. Do not use them.
- Fixture files: `baidu_search.json`, `baidu_geocode.json`, `baidu_reverse.json`,
  `baidu_suggest.json`.

### Re-test on 2026-11-27

The web route, with no credential at all:

| Endpoint | HTTP | Bytes | What came back |
|---|---|---|---|
| `?qt=s&wd=天安门&c=1&pn=0&rn=10&ie=utf-8&oue=1&from=webmap` | 200 | 281589 | `{"place_info":{…}}`, the big map payload. Only `content` holds the POI list. |
| `?qt=gc&wd=天安门广场&c=1&ie=utf-8&oue=1&from=webmap` | 200 | 714 | `{"result":{"type":35,"qid":"0050416895","qt":"gc","wd":"天安门广场","c":"1","error":0},"content":{…}}` |
| `?qt=rgc&location=39.915119,116.403963&c=1&ie=utf-8&oue=1&from=webmap` | 200 | 1249 | `{"current_city":{…},…}` |
| `https://map.baidu.com/su?wd=天安门&cid=1&type=0&pc_ver=2` | 200 | 807 | `{"q":"天安门","p":false,"t":0,"s":[…]}`, the pipe separated list |

The official API with the front-end AK:

| Endpoint | HTTP | Bytes | What came back |
|---|---|---|---|
| `place/v2/search` | 200 | 3914 | `{"status":0,"message":"ok","total":106,…}`, the first row is 天安门 at `39.915119, 116.403963` |
| `geocoding/v3` | 200 | 146 | `{"status":0,"result":{"location":{"lng":116.4041774131041,…}}}` |
| `reverse_geocoding/v3` | 200 | 851 | `{"status":0,"result":{"location":{"lng":116.40396299999995,…}}}` |

No Baidu reply carries a quota header, so the verbose mode of the tool shows no quota for Baidu.
The `total 106` of the search and the position of 天安门 are the same as on 2026-11-22.

---

## Amap (Gaode)

### How the route was found

`https://www.amap.com/` loads the JS API from
`https://webapi.amap.com/maps?v=2.0&key={front-end key}` and the page sets:

```js
window._AMapSecurityConfig = { serviceHost: '/_AMapService' }
```

The JS API then calls its backends with two extras:

```
platform=JS&s=rsv3&logversion=2.0&sdkversion=2.0&cetype=unify
```

The `serviceHost` value is the key detail. Calls go to
`https://www.amap.com/_AMapService/v3/<command>` instead of `restapi.amap.com`, and the proxy
adds the security code on the server side. Without that prefix the same request is rejected
with `USERKEY_PLAT_NOMATCH`, because the key belongs to the Web platform, not to WebService.

### Endpoints

| Purpose | Request | Result |
|---|---|---|
| Geocode | `_AMapService/v3/geocode/geo?address={a}&city={c}&{common}` | works |
| Driving route | `_AMapService/v3/direction/driving?origin={lng,lat}&destination={lng,lat}&{common}` | works |
| POI search | `_AMapService/v3/place/text?keywords={k}&city={code}&{common}` | **403** |
| Reverse geocode | `_AMapService/v3/geocode/regeo?location={lng,lat}&{common}` | risk-control reply |

Where `{common}` is `key={front-end key}&platform=JS&s=rsv3&logversion=2.0&sdkversion=2.0&cetype=unify`.

### Samples

Geocode works and returns a normal WebService body:

```json
{"status":"1","info":"OK","infocode":"10000","count":"1",
 "geocodes":[{"formatted_address":"北京市东城区天安门广场","city":"北京市",
              "district":"东城区","adcode":"110101","location":"116.397755,39.908807"}]}
```

Driving route works and returns distance and duration:

```json
{"status":"1","info":"OK","count":"1",
 "route":{"origin":"116.397428,39.908823","destination":"116.39667,39.90864",
          "paths":[{"distance":"1066","duration":"588","strategy":"速度最快"}]}}
```

### Limits found

- Every POI path answers **403 Forbidden** through the proxy: `place/text`, `place/around`,
  `place/detail`, `place/suggest`, `assistant/inputtips`. POI search is protected harder than
  the other operations, so the official channel is required for it.
- `geocode/regeo` answers with a risk-control body (`rgv587_flag`) that is not map data.
  The official channel is required for reverse geocoding.
- `restapi.amap.com` rejects the front-end key with `USERKEY_PLAT_NOMATCH`. Adding
  `platform=JS` moves the failure to `INVALID_USER_SCODE`, because the WebService API wants the
  security code as a request parameter and the front-end route only injects it server side.
- What does work on the direct channel, with no key at all: **geocode** and **driving route**.
- Fixture files: `amap_geocode.json`, `amap_driving.json`. `amap_search.json` and
  `amap_reverse.json` hold the rejected replies and exist so the failure paths stay tested.

### The v4 route

The cycling route of Amap is only on the v4 route of the official channel:

```
https://restapi.amap.com/v4/direction/bicycling?origin=<lng,lat>&destination=<lng,lat>&key=<key>
```

The v4 reply has a different shape than the v3 reply. The paths sit under `data.paths`, and a
failure is reported with `errcode` and `errmsg` instead of `status` and `info`:

```json
{"errcode": 0, "errmsg": "OK",
 "data": {"paths": [{"distance": 215, "duration": 52, "steps": [
   {"instruction": "…", "action": "…", "road": "…",
    "distance": 60, "duration": 15, "polyline": "116.397428,39.908823;…"}]}]}}
```

The quota codes of the v4 API are the same family as the v3 infocodes: `10003`, `10004`, `10009`,
`10021` and `10029`. A body with a non zero `errcode` is a failure and is never kept in the cache.

`amap_v4_route.json` holds a sample of that shape. It was **written by hand from the documented
shape**, not recorded from the live endpoint, because the trace had no Amap key of its own. Every
other fixture in this folder came from a live call.

### Re-test on 2026-11-27

| Endpoint | HTTP | Bytes | What came back |
|---|---|---|---|
| `geocode/geo?address=天安门广场&city=北京&{common}` | 200 | 359 | `{"status":"1","info":"OK","infocode":"10000","count":"1","geocodes":[{"formatted_address":"北京市东城区天安门广场","adcode":"110101","location":"116.397755,39.903182","level":"兴趣点"}]}` |
| `direction/driving?origin=116.397428,39.908823&destination=116.39667,39.90864&{common}` | 200 | 6058 | `{"status":"1","info":"OK","infocode":"10000","count":"1","route":{…}}` |
| `place/text?keywords=天安门&city=110000&{common}` | **403** | 839 | an HTML `403 Forbidden` page, not JSON |
| `geocode/regeo?location=116.397428,39.908823&{common}` | 200 | 5554 | an HTML page, not map data: the risk-control answer |

The two POI answers are the same as on 2026-11-22. The search is still blocked with 403 and the
reverse geocode is still a risk-control page that carries no `regeocode` section, so the tool
cannot use it. The geocode and the driving route still answer with data, and the tool reads them
without a key:

```
amap: ok (direct, 709 ms)
amap: channel direct, 709 ms, 1 attempt(s), from the network
```

No Amap reply carries a quota header, so the verbose mode shows no quota for Amap either.

---

## Tencent Location Service

### How the route was found

`https://map.qq.com/` loads `https://map.qq.com/api/js`, which contains two keys. One is the
JS API key. The other is a WebService key of the shape `XXXXX-XXXXX-XXXXX-XXXXX-XXXXX`, and it
is accepted by `https://apis.map.qq.com/ws/...` for the whole feature set.

### Endpoints

| Purpose | Request | Result |
|---|---|---|
| POI search | `ws/place/v1/suggestion?keyword={k}&region={r}&key={key}` | works, 100 rows |
| Reverse geocode | `ws/geocoder/v1/?location={lat,lng}&get_poi=1&key={key}` | works |
| Geocode | `ws/geocoder/v1/?address={a}&key={key}` | works, often `rate_limited` |
| Driving route | `ws/direction/v1/driving?from={lat,lng}&to={lat,lng}&key={key}` | works, often `rate_limited` |
| POI search (alt) | `ws/place/v1/search?keyword={k}&boundary=region({r},0)&key={key}` | returns an empty set |

### Samples

Suggestion returns full POI rows:

```json
{"status":0,"message":"query ok","count":100,
 "data":[{"id":"15103389097764433256","title":"天安门",
          "address":"北京市东城区东华门街道西长安街","category":"旅游景点:国家级景点",
          "location":{"lat":39.908823,"lng":116.39747}}]}
```

Reverse geocode returns the address plus the administrative division:

```json
{"status":0,"message":"Success",
 "result":{"location":{"lat":39.908823,"lng":116.39747},
           "address":"北京市东城区西长安街",
           "ad_info":{"adcode":"110101","city_code":"156110000",
                      "name":"中国,北京市,北京市,东城区"}}}
```

### Limits found

- The key is shared with the live website, so it is often busy. Under load the API answers
  HTTP 200 with a body of `{"status":120,"message":"此key每秒请求量已达到上限"}`. This is a rate
  limit, not an error and not an empty result. It must be retried with backoff.
- `place/v1/search` answers `status 0` with an empty `data` array for this key. The search
  feature is therefore built on `place/v1/suggestion`, which returns the same POI fields.
- Coordinates are **GCJ-02**, in `lat,lng` order.
- Every reply carries quota headers: `current_qps`, `limit_qps`, `current_pv`, `limit_pv`.
- Fixture files: `tencent_suggest.json`, `tencent_reverse.json`, `tencent_geocode.json`,
  `tencent_search.json`, `tencent_driving.json`.

### Re-test on 2026-11-27

| Endpoint | HTTP | Bytes | X-Limit header | What came back |
|---|---|---|---|---|
| `place/v1/suggestion` | 200 | 2315 | `current_qps=1; limit_qps=150; current_pv=364884; limit_pv=20000000000398` | `{"status":0,"message":"query ok","request_id":…}` with the POI rows |
| `place/v1/search` | 200 | 125 | `current_qps=1; limit_qps=300; current_pv=294940; limit_pv=20000000000198` | `{"status":0,"message":"Success","count":0,"data":[],"region":{"title":"北京市"}}` |
| `geocoder/v1/?address=天安门广场` | 200 | 89 | `current_qps=1; limit_qps=0; current_pv=1; limit_pv=9999999999999` | **`{"status":120,"message":"此key每秒请求量已达到上限"}`** |
| `geocoder/v1/?location=39.908823,116.39747&get_poi=1` | 200 | 3878 | `current_qps=1; limit_qps=500; current_pv=368294; limit_pv=20000000000798` | `{"status":0,"message":"Success","request_id":…}` |
| `direction/v1/driving` | 200 | 89 | `current_qps=1; limit_qps=0; current_pv=1; limit_pv=9999999999999` | **`{"status":120,"message":"此key每秒请求量已达到上限"}`** |

The shape of every reply is the same as on 2026-11-22. The search route still answers `status 0`
with an empty `data` array for this key, so the search of the tool is built on `suggestion`.

The geocode and the driving route were rate limited again on this day. Both answer HTTP 200 and
both carry `status 120`, which is a rate limit and not an error. The `limit_qps` header of those
two replies is 0, while the suggestion route showed `limit_qps=150` and the reverse geocode
`limit_qps=500` in the same run. The tool reports this as `rate_limited`:

```
tencent: rate_limited (the rate limit was hit)
tencent: channel direct, 1005 ms, 1 attempt(s), from the network, quota current_pv=368261, current_qps=1, limit_pv=20000000000398, limit_qps=150
```

The second line is the search, which did answer. The suggestion route carried the whole quota in
the one `X-Limit` header, and the tool reads that header and shows it in the verbose mode.

---

## Coordinate systems at a glance

| Provider | System | Order |
|---|---|---|
| Baidu | BD-09 | `lat,lng` |
| Amap | GCJ-02 | `lng,lat` |
| Tencent | GCJ-02 | `lat,lng` |

`mapquery` converts everything to GCJ-02 in `lng,lat` order inside the tool, and prints
whatever order the provider itself uses at the edges so the raw numbers can be checked.

---

## The Baidu Mercator problem

Baidu's web API does not return lat/lng for POI positions. It returns **BD09MC**, Baidu
Mercator metres. Every POI in a `qt=s` reply carries its position like this:

```
ext.detail_info.navi_xy.diPoint = {"x": 12958170.88, "y": 4825940.97}   best precision
ext.detail_info.point           = {"x": 12958200,    "y": 4825940}      rounded to whole metres
x = 1295817088, y = 482594097                                            the same value times 100
```

The top level `x` and `y` are the same Mercator value multiplied by 100. No field in the whole
POI record holds a plain latitude or longitude, and the `geo` string is an obfuscated encoding.
`qt=inf` and `qt=detail` do not help either.

So the tool carries the Baidu Mercator conversion with it, in `src/mapquery/mercator.py`:

```
row  = first band whose threshold is at or below |my|      (MCBAND)
u    = |my| / row[9]
lng  = row[0] + row[1] * |mx|
lat  = row[2] + row[3]*u + row[4]*u^2 + ... + row[8]*u^6
```

Two details cost real time to get right:

- The polynomial is **seven terms**, `row[2]` through `row[8]`. `row[9]` is only the divisor.
  Using it as an eighth term blows the result up by five orders of magnitude.
- The band is chosen on the **Mercator** value for the inverse, and on the **latitude** for
  the forward direction.

### How it was verified

| Check | Result |
|---|---|
| Reference vector `mc_to_ll(12958074.255013367, 3572218.8142307573)` | `(116.40309499999992, 30.7029838655178)` — exact |
| Round trip, five cities (Beijing, Shenzhen, Shanghai, Urumqi, Shenzhen) | under 2 cm |
| Baidu's own live POI payload, inverted | within 11.5 m of the independently derived position |
| Amap against Baidu for the same place | 47 m apart after normalising both to GCJ-02 |

That last row is the useful one. Amap reports 天安门 in GCJ-02 as `(116.397463, 39.909187)`.
Baidu's own live payload for 天安门, put through the Mercator inverse and then the BD-09 to
GCJ-02 step, gives `(116.3975904, 39.9087759)`. Two providers, two coordinate systems, one
place, 47 m apart.

### The GCJ-02 offset has a truncated variant

The GCJ-02 offset is published in two forms. The short form drops the sine refinement terms
and drifts **170 to 330 m** from the reference form, which is enough to break the 150 m
clustering used by `mapq compare`. The tool uses the full form.

The truncated variant is easy to copy by accident because it is shorter and it still produces
plausible looking coordinates. If a coordinate check ever looks off by a couple of hundred
metres, this is the first thing to look at.

---

## Reproducing the trace

`tools/trace_sources.py` calls every route in this document once and writes the
replies into `tests/fixtures/`. It sleeps between the calls on purpose: the shared
keys belong to live websites, and hammering them would break the tool for everyone.

`tools/smoke.py` calls every provider once and prints one status line for each of
them, without writing anything.

Run the trace when a provider changes something, then check the diff of the
fixtures before you trust it.
