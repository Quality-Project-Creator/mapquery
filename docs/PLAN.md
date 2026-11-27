# mapquery — Plan (v0.0.1)

A command-line tool that queries **Baidu Maps**, **Amap (Gaode)** and **Tencent Maps** at the
same time, converts the three different answers into one common shape, and shows them side by side.

- Version: `0.0.1`
- Language: Python 3.9+
- Interface language: English only (simple English, short sentences)
- Package: `mapquery` · CLI command: `mapq`
- Repo root: `/workspace/mapquery` (git repository, tagged `v0.0.1`)
- State: v0.0.1 is released. What has landed on top of it is in section 13.

---

## 1. The main idea

Three providers, three different APIs, three different coordinate systems. If you ask all three
the same question, the answers do not line up and the numbers are not comparable.

`mapquery` fixes that:

1. Call all three providers in parallel.
2. Normalise every answer into one small set of common data classes.
3. Put every answer on the same coordinate system before comparing them.

**No browser, no Web UI automation, no HTML scraping.** Only direct calls to the providers' own
data endpoints.

---

## 2. Two channels per provider — no key required to start

The tool talks to each provider over one of two channels.

| Channel | What it is | When it is used |
|---|---|---|
| `direct` | The provider's own front-end data route, traced and confirmed working. No account needed. | **Default.** Works on a clean install. |
| `official` | The documented WebService API, using a key the user registers (free, one minute). | Chosen automatically for any provider where the user set a key. |

The tool never *requires* a key. A key is an upgrade, not a gate.

Why this matters: the `direct` channels are shared and rate-limited, so some calls come back
"rate limited" instead of data. The tool must say so honestly instead of pretending a provider
has no results. See the status table in section 4.

---

## 3. Key decisions (and why)

| Decision | Choice | Why |
|---|---|---|
| Data access | Direct HTTP calls to provider data endpoints | Stable, fast, no browser, no HTML parsing. |
| Concurrency | `ThreadPoolExecutor` + one rate limiter per provider | HTTP is I/O bound. Threads are enough. |
| Coordinates | Convert locally with plain math | Deterministic, no quota, works offline, same answer every run. |
| Answers | One common data model per feature | Makes comparison possible. Each provider keeps its raw reply too. |
| Secrets | Environment variables, optional config file | Never in the repo. `.env` is git-ignored. |
| Errors | One provider failing never stops the others | A partial answer is still useful. |
| Dependencies | `requests`, `rich`; `pytest` for tests | Small, boring, easy to review. |

### 3.1 Coordinate systems — the core problem

| System | Used by | Notes |
|---|---|---|
| WGS-84 | Raw GPS devices | Also the normal system outside China. |
| GCJ-02 | Amap, Tencent | The China "standard" offset coordinates. |
| BD-09 | Baidu | A second offset on top of GCJ-02. |

Coordinate **order** differs too, which is a classic source of bugs:

- Baidu: `lat,lng`
- Amap: `lng,lat`
- Tencent: `lat,lng`

Plan: the tool keeps **one internal order (`lng,lat`) and one internal system (GCJ-02)**.
Every provider adapter converts at its own boundary. The user never sees the confusion.

Local transforms (closed form, no API call):

- `wgs84 -> gcj02`: the standard offset algorithm (`a = 6378245.0`,
  `ee = 0.00669342162296594323`)
- `gcj02 -> wgs84`: exact inverse by iterative refinement (3 passes, well under 1 m)
- `gcj02 -> bd09` and `bd09 -> gcj02`: the standard Baidu offset pair

### 3.2 Status vocabulary

A provider answer is always one of these, and the CLI prints it:

`ok` · `rate_limited` · `not_configured` · `not_supported` · `error` · `timeout`

A provider that is rate limited is **not** the same as a provider that returned nothing. The tool
keeps them apart and shows the channel that answered (`direct` or `official`).

---

## 4. The tracked data sources

Full trace notes, request shapes and raw samples: `docs/DATA_SOURCES.md`.

### 4.1 Baidu — direct, no key

Base `https://api.map.baidu.com/`.

The web route works with no credential at all:

| Feature | Request | Result |
|---|---|---|
| POI search | `?qt=s&wd=<kw>&c=<city>&pn=0&rn=10&ie=utf-8&oue=1&from=webmap` | OK |
| Geocode | `?qt=gc&wd=<address>&c=<city>&ie=utf-8&oue=1&from=webmap` | OK |
| Reverse geocode | `?qt=rgc&location=<lat,lng>&c=<city>&ie=utf-8&oue=1&from=webmap` | OK |
| Suggest | `https://map.baidu.com/su?wd=<kw>&cid=1&type=0&pc_ver=2` | OK |

Better still, the AK that Baidu ships in its own page bundle is accepted by the **official**
WebService API, so search, geocode, reverse geocode and detail all work through the documented
endpoints and return plain BD-09 coordinates. Only the routing service is switched off on that
shared AK, so driving and transit routes need a user key.

The web route returns POI positions in BD09MC (Baidu Mercator metres), so the tool carries that
conversion too. It was verified to better than one centimetre and it also confirmed the
official API results exactly.

### 4.2 Amap — direct, via the front-end service route

Base `https://www.amap.com/_AMapService/v3/`. Needs the front-end key and the JS parameter set:

```
key=<front-end key>&platform=JS&s=rsv3&logversion=2.0&sdkversion=2.0&cetype=unify
```

| Feature | Request | Result |
|---|---|---|
| Geocode | `geocode/geo?address=<a>&city=<c>&…` | **OK** |
| Driving route | `direction/driving?origin=<lng,lat>&destination=<lng,lat>&…` | **OK** |
| POI search | `place/text?keywords=<k>&city=<code>&…` | **403** — blocked by the proxy |
| Reverse geocode | `geocode/regeo?location=<lng,lat>&…` | Risk-control reply, not data |

The official channel (`restapi.amap.com/v3/…`) works for everything but needs a user key.

The cycling route of Amap is only on the **v4** route (`restapi.amap.com/v4/direction/bicycling`).
The v4 reply has a different shape: the paths are under `data.paths`, not under `route.paths`, and
a failure is reported with `errcode` and `errmsg` instead of `status` and `info`. The parser reads
both shapes, and the quota codes of the v4 API are the same family as the v3 infocodes.

### 4.3 Tencent — direct, via the front-end key

Base `https://apis.map.qq.com/ws/`. The front-end key is accepted by the WebService API.

| Feature | Request | Result |
|---|---|---|
| POI search | `place/v1/suggestion?keyword=<k>&region=<r>&key=<k>` | **OK**, 100 rows |
| Reverse geocode | `geocoder/v1/?location=<lat,lng>&get_poi=1&key=<k>` | **OK** |
| Geocode | `geocoder/v1/?address=<a>&key=<k>` | OK endpoint, `rate_limited` under load |
| Driving route | `direction/v1/driving?from=<lat,lng>&to=<lat,lng>&key=<k>` | OK endpoint, `rate_limited` under load |
| POI search | `place/v1/search?keyword=…&boundary=…` | Returns an empty set for this key |

So Tencent search is built on `suggestion`, which carries the same POI fields.

### 4.4 Capability matrix for v0.0.1

| Feature | Baidu | Amap | Tencent |
|---|---|---|---|
| POI search | direct | official key | direct (`suggestion`) |
| Geocode | direct | direct | direct |
| Reverse geocode | direct | official key | direct |
| Driving route | official key | direct | direct |
| Walking / cycling route | — | official key | direct |
| Transit route | — | official key | direct |
| District | — | official key | direct |
| Weather | — | official key | — |

A dash means the provider does not offer that feature. The CLI prints `not_supported` — it
never fakes a result.

---

## 5. Feature list for v0.0.1

### 5.1 Commands

```
mapq search <keyword>              # POI search
      [--city CITY] [--near lng,lat] [--radius M] [--limit N] [--types WORDS]

mapq geocode <address>             # address -> coordinates
      [--city CITY]

mapq reverse <lng,lat>             # coordinates -> address

mapq route <from> <to>             # route between two places
      [--mode driving|walking|cycling|transit] [--city CITY]
      # <from>/<to> accept "116.397,39.909" or a text address

mapq matrix --from "a;b" --to "c;d"   # distance matrix between many points

mapq compare <keyword>             # headline feature: query all three, diff the answers
      [--city CITY] [--near lng,lat] [--radius M] [--limit N] [--types WORDS]
      [--cluster-radius M] [--name-ratio F] [--same-place-radius M]

mapq convert --from <sys> --to <sys> <lng,lat>   # wgs84 | gcj02 | bd09

mapq district <keyword>            # administrative districts
mapq weather <adcode>              # Amap only, clearly labelled

mapq providers [--channel direct|official]   # config status + capability matrix
mapq config show|set|init          # manage API keys
```

**The types filter is in the code now.** v0.0.1 left it out: a types filter was thought to need
a search endpoint that takes a type parameter, and the only Amap search route is blocked
(HTTP 403) on the direct channel, so it could not work for all three providers yet. The filter
that landed does not need such an endpoint. It works on the words that the provider itself gave,
so the same words can be used for every provider: a place is kept when one of the wanted words is
in its category or in its name. It lives in `src/mapquery/filters.py` and is used by `search`
and by `compare`. The words are separated by commas or by semicolons, and an empty entry is a
usage mistake. With a filter the exit code is 0 when at least one provider kept a place of the
wanted types, and 1 when no place of the wanted types was left.

### 5.2 Global flags

```
--providers baidu,amap,tencent     # pick which providers to call
--json / --table / --csv           # output format (default: table)
--jobs N                           # worker threads (default 8)
--timeout S                        # per-request timeout (default 10)
--retries N                        # retry attempts (default 2)
--no-cache                         # skip the local result cache
--verbose                          # timings, channel, quota headers
--version
```

### 5.3 What `compare` produces

1. A table: name, provider, distance from the search centre, address.
2. **Clusters**: places that are clearly the same POI across providers, matched by name
   similarity plus distance (under 150 m after coordinate normalisation).
3. **Consensus**: which places all three providers agree on.
4. **Spread**: average and maximum distance between providers for the same place.

This is the part that makes the tool worth having. Raw API calls are easy; comparing them
correctly is the actual job.

---

## 6. Code layout

```
/workspace/mapquery/
├── pyproject.toml
├── README.md
├── README.zh-CN.md               # the Chinese readme
├── .gitignore
├── docs/
│   ├── PLAN.md                     # this file
│   └── DATA_SOURCES.md             # the traced endpoints, with raw samples
├── src/mapquery/
│   ├── __init__.py                 # __version__ = "0.0.1"
│   ├── __main__.py                 # python -m mapquery
│   ├── cli.py                      # argparse commands, argument wiring
│   ├── config.py                   # env vars + config file, key lookup
│   ├── models.py                   # Place, Route, GeoResult, ProviderResult
│   ├── coords.py                   # wgs84 / gcj02 / bd09 transforms
│   ├── mercator.py                 # the Baidu Mercator metres
│   ├── http.py                     # session, retries, backoff, rate limiter
│   ├── cache.py                    # small disk cache for repeated queries
│   ├── engine.py                   # thread pool, fan-out, merge, partial failure
│   ├── compare.py                  # clustering + consensus + spread
│   ├── filters.py                  # the filter on the types of the places
│   ├── render.py                   # table / json / csv output
│   └── providers/
│       ├── __init__.py             # provider registry
│       ├── base.py                 # Provider base class
│       ├── baidu.py                # direct + official
│       ├── amap.py                 # direct + official
│       ├── tencent.py              # direct + official
│       └── direct_keys.py          # the keys of the direct channel
├── tools/
│   ├── trace_sources.py           # re-record the traced replies
│   ├── smoke.py                    # one live call per provider
│   └── check_readmes.py            # check that the two readmes agree
└── tests/
    ├── conftest.py
    ├── fixtures/                   # recorded real responses (JSON)
    ├── test_cache.py
    ├── test_cli.py
    ├── test_compare.py
    ├── test_config.py
    ├── test_coords.py
    ├── test_engine.py
    ├── test_http.py
    ├── test_mercator.py
    ├── test_providers.py
    ├── test_readme.py
    ├── test_render.py
    └── test_tools.py
```

---

## 7. Concurrency and rate limiting

- One `ThreadPoolExecutor`, `max_workers = --jobs` (default 8).
- One **token-bucket limiter per provider**, so a slow provider cannot starve the others and no
  provider is called above its limit.
  - Baidu: 20 requests/second (default per-IP limit)
  - Amap: 3 requests/second
  - Tencent: 5 requests/second
  - All three configurable in the config file.
- Retries with exponential backoff and jitter on: timeout, HTTP 429, HTTP 5xx, **and provider
  level rate limits** — Tencent `status 120`, Amap `infocode 10003/10004/10021/10009`, Baidu
  `status 4`. A `Retry-After` header wins over the backoff.
- Bad request errors (HTTP 4xx other than 429, and provider "bad parameter" codes) are **not**
  retried.
- Timeouts: connect 3.1 s, read 10 s, both configurable.
- One `requests.Session` per thread (thread-local) so connections are pooled and reused.
- Results come back in a **fixed provider order**, never completion order, so output is stable.
- If one provider fails, the others still answer. Each result carries its own status.
- Exit codes: `0` = at least one provider answered (a provider that answers with no place
  still counts as an answer), `1` = no provider answered with data (every provider failed,
  or the matrix could not find the places, or no place of the wanted types was left),
  `2` = wrong usage, `130` = the command was stopped with Ctrl-C.

---

## 8. Secrets

Read from the environment first, then an optional config file (`~/.config/mapquery/config.toml`).

| Provider | Variable | Extra |
|---|---|---|
| Baidu | `BAIDU_MAP_AK` | `BAIDU_MAP_SK` for signature checking |
| Amap | `AMAP_API_KEY` | `AMAP_SECRET_KEY` for digital signing |
| Tencent | `TENCENT_MAP_KEY` | `TENCENT_MAP_SK` for signature checking |

Rules: keys are never printed in full (only a mask such as `...f3a9`), never written to the
repo, never stored in the result cache.

The `direct` channel ships with the front-end keys already found by the trace. They are shared
with the providers' own websites, so they are rate limited. The README explains this and tells
the user how to switch to their own key for steady use.

---

## 9. Git plan

`git init -b main`, then one small commit per step, so the history reads like a build log:

```
chore: scaffold project, packaging, gitignore
docs: add plan and traced data sources
feat: add config, models, coordinate transforms
feat: add http layer with retries and rate limiting
feat: add concurrent engine and cache
feat: add baidu provider
feat: add amap provider
feat: add tencent provider
feat: add cli commands and output rendering
feat: add cross-provider compare
test: add fixtures and unit tests
docs: add readme
chore: release v0.0.1
```

Then `git tag -a v0.0.1 -m "v0.0.1"`. No remote unless the user gives one.

---

## 10. Verification plan

1. **Unit tests, no network** — coordinate round-trips, parsing against recorded fixtures, engine
   behaviour with mocked HTTP, CLI smoke tests.
2. **Live check** — one call per provider against the real endpoints, then `mapq compare`.
3. **Coordinate cross-check** — compare the local transform with the providers' own conversion
   endpoints; they must agree within a few metres.
4. **Concurrency check** — a 30-query batch must not exceed any provider's rate limit, and the
   output order must be stable.
5. **Failure check** — point one provider at a bad key; the other two must still answer.

Acceptance bar: `pytest` fully green, the CLI runs from a clean checkout after
`pip install -e .`, and `mapq compare` prints a correct side-by-side table for one known place.

---

## 11. Division of work

| Who | Does what |
|---|---|
| **Mavis** | Owns this plan, the git history, the trace and the secrets. Reviews each commit, runs the final acceptance checks. |
| **Coder** | Writes the code, through the Task tool in small steps. Each step is reviewed before the next one starts. |
| **Verifier** | Adversarial review at the end: tries to break concurrency, error handling, coordinate maths, key handling and CLI edge cases. |

The team that works on the repository today: **Chief** takes the final call, **代码实现** owns
`src/**` and the v0.0.2 features, **测试验证** is the independent verifier and only writes a
report, **文档数据源** owns `README.md`, `README.zh-CN.md` and `docs/**`, and **发布运维** owns
`.github/**`, the license and the tags. The files stay separated, so nobody edits the work of
another role.

All data-source work is done by calling the real endpoints and recording the replies as test
fixtures. Nothing comes from a map web page.

---

## 12. Out of scope for v0.0.1

- Map rendering and any kind of Web UI.
- Transit timetables, fares and live traffic layers.
- An interactive Python REPL — one-shot commands only.
- Any paid API tier.
- Publishing to PyPI or a public git remote.

---

## 13. What has changed after v0.0.1

v0.0.1 is the release this plan was written for. The code that is in the tree now already
carries more than the plan describes. This section keeps the difference on the record, so that
the plan is not read as a promise about the code.

### The types filter

It is implemented, in `src/mapquery/filters.py`, and both `search` and `compare` take it as
`--types WORDS`. The reason it was left out in v0.0.1 turned out to be wrong: the filter does
not need a search endpoint that takes a type parameter, it works on the words that the provider
gave in its own category and its own name.

### The grouping rules of `compare`

`compare` takes `--cluster-radius`, `--name-ratio` and `--same-place-radius`. The values
of the plan are still the defaults, 150 metres, 0.55 and 25 metres, but they are now settings
that can be changed per run and in the config file. The config file of a new run holds them
next to `timeout`, `connect_timeout`, `retries` and `jobs`.

### The other options that the plan did not name

| Option | Where |
|---|---|
| `--types WORDS` | `search`, `compare` |
| `--cluster-radius M` | `compare` |
| `--name-ratio F` | `compare` |
| `--same-place-radius M` | `compare` |
| `--city CITY` | `route` — the transit route of Amap needs the city of the start point |
| `--channel direct\|official` | `providers` — shows the other channel without using it |

### The trace was run again on 2026-11-27

Every route was called once more, one endpoint at a time. The results, the HTTP status of every
reply and the quota headers are in `docs/DATA_SOURCES.md`. Nothing changed: Amap still answers
403 on the POI routes and a risk-control page on the reverse geocode, the search of Tencent is
still empty for the shared key, and the geocode and the driving route of Tencent were rate
limited again.

### The two readmes are checked by a script

`tools/check_readmes.py` checks that both readmes name every command and every key.
`tests/test_readme.py` checks the promises that the English readme makes. The Chinese readme
carries the same content and has to be changed together with the English one.
