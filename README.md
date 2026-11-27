# mapquery

`mapquery` asks Baidu Maps, Amap and Tencent Maps the same question at the same time.
It turns the three different answers into one common shape and puts them side by side.
Then it tells you where the providers agree and where they do not.

No API key is needed to start.

---

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

After that the command `mapq` is available.

You can also run the tool without installing it:

```bash
PYTHONPATH=src python -m mapquery --version
```

The tool needs Python 3.9 or later. It uses `requests` and `rich`, and nothing else.

---

## Quick start

Three commands and what they really print.

### 1. Search for places

```bash
mapq search 天安门 --city 北京 --limit 3
```

```
baidu: ok (direct, 1051 ms) | amap: not_configured (no AMAP_API_KEY) | tencent: ok (direct, 1015 ms)

 provider │ name            │ address                                  │ category              │        lng │       lat
──────────┼─────────────────┼──────────────────────────────────────────┼───────────────────────┼────────────┼───────────
 baidu    │ 天安门          │ 北京市东城区长安街                       │ 旅游景点;文物古迹     │  116.39759 │ 39.908776
 baidu    │ 天安门广场      │ 北京市东城区东长安街                     │ 旅游景点;文物古迹     │ 116.397799 │ 39.903307
 baidu    │ 天安门东        │ 地铁1号线八通线                          │ 交通设施;地铁站       │  116.40154 │ 39.907736
 tencent  │ 天安门          │ 北京市东城区东华门街道西长安街           │ 旅游景点:国家级景点   │  116.39747 │ 39.908823
 tencent  │ 天安门广场      │ 北京市东城区东长安街                     │ 旅游景点:风景名胜     │ 116.397827 │  39.90374
 tencent  │ 天安门广场-国旗 │ 北京市东城区东长安街与广场东侧路交叉口西 │ 旅游景点:其它旅游景点 │  116.39757 │ 39.90693
          │                 │ 南方向174米左右                          │                       │            │
```

The first line is the status of every provider. It says who answered, on which
channel, and how long it took.

### 2. Compare the answers

```bash
mapq compare 天安门 --city 北京 --limit 5
```

```
baidu: ok (direct, 1167 ms) | amap: not_configured (no AMAP_API_KEY) | tencent: ok (direct, 1032 ms)

                                                     Places
 provider │ name             │ address                                                 │        lng │       lat
──────────┼──────────────────┼─────────────────────────────────────────────────────────┼────────────┼───────────
 baidu    │ 天安门           │ 北京市东城区长安街                                      │  116.39759 │ 39.908776
 baidu    │ 天安门广场       │ 北京市东城区东长安街                                    │ 116.397799 │ 39.903307
 baidu    │ 天安门东         │ 地铁1号线八通线                                         │  116.40154 │ 39.907736
 baidu    │ 天安门西         │ 地铁1号线八通线                                         │ 116.391652 │ 39.907463
 baidu    │ 天安门-城楼      │ 北京市东城区西长安街天安门                              │ 116.397573 │ 39.908744
 tencent  │ 天安门           │ 北京市东城区东华门街道西长安街                          │  116.39747 │ 39.908823
 tencent  │ 天安门广场       │ 北京市东城区东长安街                                    │ 116.397827 │  39.90374
 tencent  │ 天安门广场-国旗  │ 北京市东城区东长安街与广场东侧路交叉口西南方向174米左右 │  116.39757 │ 39.90693
 tencent  │ 天安门东[地铁站] │ 地铁1号线八通线                                         │ 116.401273 │ 39.907773
 tencent  │ 天安门城楼       │ 北京市东城区东长安街天安门广场北侧                      │ 116.397513 │ 39.908739

                                        Clusters
 id │ name            │ providers      │ members │        lng │       lat │ spread_max_m
────┼─────────────────┼────────────────┼─────────┼────────────┼───────────┼──────────────
  1 │ 天安门          │ baidu, tencent │       4 │ 116.397537 │  39.90877 │         12.5
  2 │ 天安门广场      │ baidu, tencent │       2 │ 116.397813 │ 39.903523 │         48.2
  3 │ 天安门东        │ baidu, tencent │       2 │ 116.401407 │ 39.907755 │         23.1
  4 │ 天安门西        │ baidu          │       1 │ 116.391652 │ 39.907463 │          0.0
  5 │ 天安门广场-国旗 │ tencent        │       1 │  116.39757 │ 39.90693 │          0.0

                    Consensus
 id │ name       │ providers      │ spread_max_m
────┼────────────┼────────────────┼──────────────
  1 │ 天安门     │ baidu, tencent │         12.5
  2 │ 天安门广场 │ baidu, tencent │         48.2
  3 │ 天安门东   │ baidu, tencent │         23.1

Spread: 3 clusters with more than one place, max 48.2 m, mean 27.9 m

Skipped:
  amap: Amap (Gaode) needs the key AMAP_API_KEY for search
```

The first table holds the places that the providers returned. The second one
groups them, the third one holds the groups that every provider that answered
agrees on.

### 3. Change a point from one coordinate system to another

```bash
mapq convert --from bd09 --to gcj02 116.403963,39.915119
```

```
 from_system │ to_system │         lng │        lat
─────────────┼───────────┼─────────────┼────────────
 bd09        │ gcj02     │ 116.3975904 │ 39.9087759
```

---

## The three providers

| Name | Provider | Home |
|---|---|---|
| `baidu` | Baidu Maps | https://map.baidu.com |
| `amap` | Amap (Gaode) | https://www.amap.com |
| `tencent` | Tencent Maps | https://map.qq.com |

Every provider has two channels.

### The direct channel

The direct channel is the default. It needs no account and no key.
It uses the data routes that the providers' own websites call.
Those routes carry keys that are shipped inside the public page bundles of
the providers.

Those keys are shared with millions of other people. That has two results:

- The routes are fast and free, and they work right after the install.
- The routes are rate limited. A busy minute gives you `rate_limited`, not
  data. The tool says so, it does not pretend the answer was empty.

The direct channel of Baidu uses the official WebService API with the AK
from Baidu's own page bundle. The web route of `map.baidu.com` is the
fallback for it. The direct channel of Tencent uses the WebService API of
`apis.map.qq.com` with the front-end key. The direct channel of Amap uses
the service route of `www.amap.com`.

### The official channel

The official channel is the documented WebService API of the provider.
It needs a key of your own. You get one for free from the website of the
provider, in about a minute.

Put the key in the environment and that provider switches to the official
channel. The official channel has a better quota, it is not shared with
anybody, and it can do more:

| Provider | Environment variable | Extra |
|---|---|---|
| Baidu | `BAIDU_MAP_AK` | `BAIDU_MAP_SK` |
| Amap | `AMAP_API_KEY` | `AMAP_SECRET_KEY` |
| Tencent | `TENCENT_MAP_KEY` | `TENCENT_MAP_SK` |

```bash
export AMAP_API_KEY="your key here"
mapq providers
```

The `providers` command shows the channel of every provider and what it
can do. A key is never printed in full. You only ever see the last four
characters, such as `...f3a9`.

You can also keep the keys in a file:

```bash
mapq config init          # writes ~/.config/mapquery/config.toml
mapq config set amap key "your key here"
mapq config show          # shows the settings, the keys are masked
```

A new config file starts with the settings of the tool:

```toml
timeout = 10
connect_timeout = 3.1
retries = 2
jobs = 8
cluster_radius = 150.0
name_ratio = 0.55
same_place_radius = 25.0
```

The connect timeout is the time that the tool waits for the connection,
the timeout is the time that it waits for the answer. The last three
settings are the rules of the `compare` command.

The environment always wins over the file.

The file is written with the rights of your user only, because it holds
the keys. A file that cannot be parsed is never used and never
overwritten: the tool names the file, says that it is ignored and keeps
working with the environment.

---

## The commands

### `mapq search <keyword>`

Search for places.

```bash
mapq search 天安门 --city 北京 --limit 3
```

Options: `--city`, `--near lng,lat`, `--radius M`, `--limit N`,
`--types WORDS`.

With `--near` the tool also shows the distance from that point. A nearby
search is not possible on the direct channel of Baidu and of Tencent, so
Baidu reports `not_configured` (its official channel can do it, one key of
your own opens it) and Tencent reports `not_supported` (no channel of
Tencent can do it). Amap reports `not_configured`, because it cannot
search at all without a key of your own. The other providers still answer.

`--types` keeps only the places whose category or whose name holds one of
the words. The words are separated by commas or by semicolons, and every
provider uses its own words for a type, so the same words are used for all
of them. With a filter the exit code is 0 when at least one provider kept a
place of the wanted types, and 1 when no place of the wanted types was left.

A search without a keyword, a geocode without an address, an empty
`--city`, an empty `--providers` and a limit below 1 are usage mistakes.
The tool stops with the exit code 2 and says what is wrong, before it calls
a provider.

### `mapq geocode <address>`

Turn an address into a point.

```bash
mapq geocode 天安门广场 --city 北京
```

```
baidu: ok (direct, 1133 ms) | amap: ok (direct, 1051 ms) | tencent: rate_limited (the rate limit was hit)

 provider │ address                │        lng │        lat │ level
──────────┼────────────────────────┼────────────┼───────────┼──────────
 baidu    │ -                      │   116.3978 │ 39.903307 │ 旅游景点
 amap     │ 北京市东城区天安门广场 │ 116.397755 │ 39.903182 │ 兴趣点
```

Options: `--city`.

### `mapq reverse <lng,lat>`

Turn a point into an address. The point is written as `lng,lat`.

```bash
mapq reverse 116.3975904,39.9087759
```

```
baidu: ok (direct, 1007 ms) | amap: not_configured (no AMAP_API_KEY) | tencent: ok (direct, 931 ms)

 provider │ address                            │        lng │       lat │ level
──────────┼────────────────────────────────────┼────────────┼───────────┼────────
 baidu    │ 北京市东城区东华门街道中华路甲10号 │ 116.397591 │ 39.908776 │ 东城区
 tencent  │ 北京市东城区西长安街               │  116.39759 │ 39.908776 │ -
```

A point that is not `lng,lat` is a usage mistake. The tool stops with the
exit code 2 and says what the format should be.

### `mapq route <from> <to>`

Find a route between two places. Each end is either `lng,lat` or a text
address. An address is geocoded first, with the same provider.

```bash
mapq route 天安门 116.39667,39.90864 --mode driving
```

```
baidu: not_configured (no BAIDU_MAP_AK) | amap: ok (direct, 883 ms) | tencent: rate_limited (the rate limit was hit)

 provider │ mode    │ distance_m │ distance_km │ duration_min
──────────┼─────────┼────────────┼─────────────┼──────────────
 amap     │ driving │     1026.0 │       1.026 │          8.8

Steps:
  amap (driving):
    1. 向北行驶396米左转 (396 m)
    2. 沿东华门路向西行驶101米左转 (101 m)
    3. 向南行驶157米向左前方行驶 (157 m)
    4. 向东南行驶7米靠左 (7 m)
    5. 向东南行驶21米向右前方行驶 (21 m)
```

Modes: `driving`, `walking`, `cycling`, `transit`. Every provider has its
own name for a mode, so `cycling` becomes `bicycling` for Amap and for
Tencent. A provider that cannot do the mode says so.

Options: `--mode`, `--city`. The transit route of Amap needs the city of
the start point, so `--city` has to be given for a transit route of Amap.

The route of Baidu needs a key of your own. The routing service is switched
off on the shared AK, so the direct channel of Baidu reports
`not_configured`. With a key of your own the Baidu channel does routes, but
only driving ones: Baidu has no walking, cycling or transit route at all, so
those modes report `not_supported` on every channel.

### `mapq matrix --from "a;b" --to "c;d"`

Straight line distances between many points. The points are `lng,lat` or
addresses. The distances are computed on your own machine.

```bash
mapq matrix --from "116.397428,39.908823;天安门" --to "116.39667,39.90864;天安门广场"
```

```
baidu: ok (direct, 1580 ms) | amap: ok (direct, 1297 ms) | tencent: rate_limited (the rate limit was hit)

  Straight line distance in metres. This is not a road
                       distance.
 from                 │ 116.39667,39.90864 │ 天安门广场
──────────────────────┼────────────────────┼────────────
 116.397428,39.908823 │               67.8 │      614.2
 天安门               │               79.9 │      608.4
```

These are straight line distances. They are not road distances and they are
not walking distances.

An address in the matrix is geocoded with a provider that really answers.
The providers are tried in turn, so a rate limited provider does not stop
the others. The status line shows every provider that was asked, with its
own status. When no provider can find a place, the command says so and
stops with the exit code 1. That is the same exit code as "every provider
failed": it means that no provider answered with data.

Both lists are required. A list with no point in it is a usage mistake, and
the tool stops with the exit code 2.

### `mapq compare <keyword>`

The headline feature. It asks every provider, groups the answers that are
the same place, and measures the distance between the providers. The
[next section](#the-compare-feature) explains the numbers.

```bash
mapq compare 天安门 --city 北京 --limit 5
```

Options: `--city`, `--near lng,lat`, `--radius M`, `--limit N`,
`--types WORDS`, `--cluster-radius M`, `--name-ratio F`,
`--same-place-radius M`.

The last three are the rules of the grouping. The default of
`--cluster-radius` is 150 metres, the default of `--name-ratio` is 0.55 and
the default of `--same-place-radius` is 25 metres. The option wins over the
config file, and the config file wins over the built-in default.

### `mapq convert --from <system> --to <system> <lng,lat>`

Change a point from one coordinate system to another. This one is local,
so it always works and it never needs a network.

```bash
mapq convert --from bd09 --to gcj02 116.403963,39.915119
```

Systems: `wgs84`, `gcj02`, `bd09`. Both `--from` and `--to` are
required, and a system that is not one of the three is a usage mistake.

### `mapq district <keyword>`

Show the administrative districts of a place.

```bash
mapq district 北京
```

### `mapq weather <adcode>`

Show the weather of an area code. Only Amap can do this.

```bash
mapq weather 110101
```

The weather is always Amap. If you use `--providers`, Amap must be in the
list. Otherwise the command stops with the exit code 2 and says that the
selected providers cannot do the weather.

If Amap is not configured the tool says so and stops. It does not fail
the other work.

### `mapq providers`

Show the providers, the channel that will be used, the key status and the
capability matrix.

```bash
mapq providers
```

```
                                               Providers
 provider │ name         │ channel │ key     │ search │ geocode │ reverse │ route │ district │ weather
──────────┼──────────────┼─────────┼─────────┼────────┼─────────┼─────────┼───────┼──────────┼─────────
 baidu    │ Baidu Maps   │ direct  │ not set │ yes    │ yes     │ yes     │ no    │ no       │ no
 amap     │ Amap (Gaode) │ direct  │ not set │ no     │ yes     │ no      │ yes   │ no       │ no
 tencent  │ Tencent Maps │ direct  │ not set │ yes    │ yes     │ yes     │ yes   │ yes      │ no

                                         Route modes and limits
 provider │ channel │ modes                                │ limits
──────────┼─────────┼──────────────────────────────────────┼────────────────────────────────────────────
 baidu    │ direct  │ -                                    │ a nearby search needs the official channel
 amap     │ direct  │ driving                              │ -
 tencent  │ direct  │ bicycling, driving, transit, walking │ a nearby search is not available

A key of your own opens:
  baidu: the official channel opens route
  amap: the official channel opens district, reverse, search, weather
```

The first table holds the features of the channel that will be used. The
second one holds the route modes and the limits of that channel. The lines
under them say what a key of your own would open.

Options: `--channel direct|official`. It shows the other channel without
using it, so you can see what a key of your own would change.

### `mapq config show|set|init`

Look at the settings and manage the keys. See
[the channels](#the-direct-channel).

```bash
mapq config show                     # the settings and the masked keys
mapq config set amap key "your key"  # write one key to the config file
mapq config set amap key             # the value is asked for, not shown
mapq config init                     # create the config file
```

`config set` takes the name of the provider, the name of the key and the
value. The key names are `ak` and `sk` for Baidu, `key` and `secret` for
Amap, `key` and `sk` for Tencent. When the value is left out, the tool asks
for it and does not show what you type. A key name that the provider does
not have is a usage mistake, and the tool stops with the exit code 2.

---

## Output formats

Every command that talks to the providers prints one status line:

```
baidu: ok (direct, 142 ms) | amap: not_configured (no AMAP_API_KEY)
```

The line is always there, so you always know who answered.

An answer that came from the local cache says so:

```
tencent: ok (direct, cached, 3 ms)
```

The cache lives in `~/.cache/mapquery`. Put it somewhere else with the
environment variable `MAPQUERY_CACHE_DIR`, or turn it off with `--no-cache`.

| Format | Flag | Where it goes |
|---|---|---|
| Table | `--table` (the default) | The status line and the table go to the standard output. |
| JSON | `--json` | The status of every provider is under the `providers` key. |
| CSV | `--csv` | The rows go to the standard output. The status line goes to the error output, so the file stays clean. |

```bash
mapq search 天安门 --city 北京 --json
mapq search 天安门 --city 北京 --csv > places.csv
```

The JSON output holds the facts of every call: the status, the channel, the
time, the number of attempts, the flag `cached` and the quota headers of
the answer.

The CSV output of the compare command holds the places first, then the
clusters, then the consensus. A row with `[places]`, `[clusters]` or
`[consensus]` in the first column marks the section that comes after it.
The cluster rows use the same columns as the place rows: the provider
column holds the providers of the cluster, the point columns hold the
centre of the cluster, and the two extra columns hold the number of places
and the largest distance.

The global options work before the command and after it:

```bash
mapq --json search 天安门
mapq search 天安门 --json
```

Only one format can be used. `--json` together with `--csv` stops the
command with the exit code 2.

Other global options:

| Option | Meaning |
|---|---|
| `--providers baidu,amap` | Call only these providers. An empty list is a usage mistake. |
| `--jobs N` | How many providers are called at the same time. The default is 8. |
| `--timeout S` | The read timeout of one request in seconds. The default is 10. |
| `--retries N` | How many times a failed request is tried again. The default is 2. |
| `--no-cache` | Do not use the local cache. |
| `--verbose` | Print more about what happens. |
| `--version` | Print the version. |

The verbose mode adds one line for every provider under the status line.
It holds the channel, the time, the number of attempts, the place the
answer came from and the quota headers, when there are any:

```
baidu: channel direct, 142 ms, 1 attempt(s), from the network
tencent: channel direct, 931 ms, 1 attempt(s), from the network, quota current_pv=368261, current_qps=1, limit_pv=20000000000398, limit_qps=150
```

A provider that was never called has no attempts and the line says that no
request was made.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | At least one provider answered with data, or the matrix could be computed. |
| 1 | No provider answered with data: every provider failed, or the matrix could not find the places. |
| 2 | The command was used in the wrong way, such as a bad point or an empty keyword. |
| 130 | The command was stopped with Ctrl-C. |

---

## Coordinate systems

The three providers use two coordinate systems and two different orders:

| Provider | System | Order |
|---|---|---|
| Baidu | BD-09 | `lat,lng` |
| Amap | GCJ-02 | `lng,lat` |
| Tencent | GCJ-02 | `lat,lng` |

BD-09 is a second offset on top of GCJ-02. The two together move a point
by a few hundred metres, which is more than enough to break a comparison.

The tool keeps one order and one system inside: the order is `lng,lat` and
the system is GCJ-02. Every provider converts at its own border, so you
never see the mess.

One more thing about Baidu. The web route of Baidu does not give a plain
latitude and longitude for a place. It gives Baidu Mercator metres. The
tool carries the conversion for it, in `src/mapquery/mercator.py`, and the
numbers agree with the official API to the centimetre.

---

## The compare feature

`mapq compare` is the reason this tool exists. Three APIs answer the same
question in three different ways. The raw answers are easy to get. The
hard part is to say whether they mean the same place.

The tool does this in four steps.

**1. Normalise the names.** Every name is put in the normal form of
Unicode, the spaces are taken away and the letters are made small. So
`"Tiananmen  Square"` and `"tiananmen square"` are the same name.

The name matcher works inside one script. It cannot bridge two scripts:
`"Tiananmen Square"` and `"天安门广场"` have a name ratio of 0.000, so
they are never matched by name. A Latin query against Chinese names is
matched by position and by the 25 metre rule, and the position based
rule is what carries it.

**2. Match the places.** Two places of different providers are the same
place when both of these are true:

- they are less than 150 metres apart, and
- the names look alike, with a similarity of 0.55 or more.

Two places that are less than 25 metres apart are the same place, even when
the names are different. That is the same building. This rule holds for
any two places, no matter which provider they came from, so two places of
one provider that are 25 metres apart are the same place too.

**3. Build the clusters.** The matched places are grouped. A cluster holds
the places that are all the same place. A cluster can hold several places
of one provider, because a provider can answer with the same place twice.

**4. Measure the spread.** Every cluster gets a centre, which is the mean
of the places in it, and two numbers:

- `spread_max_m`: the largest distance between two places of the cluster.
  This is the worst case.
- `spread_mean_m`: the mean distance between the places of the cluster.
  This is the usual case.

A cluster is a chain of matches, so the spread of a cluster can be bigger
than the distance that was used to match. The `spread_max_m` column is
the number to look at.

### What the output means

| Name | Meaning |
|---|---|
| Places | The rows that the providers returned. |
| Clusters | The groups of places that are the same place. |
| Consensus | The clusters that hold every provider that answered. |
| Spread | The summary over all the clusters with more than one place: the count, the largest spread and the mean spread. |
| Skipped | The providers that did not answer, and why. |

The consensus is only judged against the providers that really answered.
If Amap cannot search, the consensus is about Baidu and Tencent only. The
tool tells you that Amap was skipped, and why.

A spread of a few metres is normal. Baidu and Tencent are both in GCJ-02,
so they should be close. A spread of 50 metres means that the two
providers point at slightly different things, such as the gate and the
square.

---

## Limits and honesty

This is what works without a key of your own, on the direct channel:

| Feature | Baidu | Amap | Tencent |
|---|---|---|---|
| POI search | yes | needs `AMAP_API_KEY` | yes |
| Geocode | yes | yes | yes |
| Reverse geocode | yes | needs `AMAP_API_KEY` | yes |
| Driving route | needs `BAIDU_MAP_AK` | yes | yes |
| Walking route | no | needs `AMAP_API_KEY` | yes |
| Cycling route | no | needs `AMAP_API_KEY` | yes |
| Transit route | no | needs `AMAP_API_KEY` | yes |
| District | no | needs `AMAP_API_KEY` | yes |
| Weather | no | needs `AMAP_API_KEY` | no |

"Needs a key" means that the feature is only there on the official
channel, so you have to set the key of that provider. A "no" means that
the provider does not have that feature at all. Baidu only has driving
routes in this tool.

The cycling route of Amap is on the v4 route of the official channel, and
the cycling route of Tencent is on `direction/v1/bicycling`. The name of
the mode is `bicycling` for both of them.

A few more honest notes:

- A provider that is rate limited is reported as `rate_limited`. That is
  not the same as a provider with no results. The tool never turns a
  rate limit into an empty answer.
- A provider that cannot do a feature is reported as `not_supported`.
  A provider that could do it but has no key is reported as
  `not_configured`.
- A nearby search is not possible on the direct channel of Baidu and of
  Tencent. Baidu reports `not_configured`, because its official channel
  can do it. Tencent reports `not_supported`, because no channel of
  Tencent can do it.
- The shared keys of the direct channel belong to the live websites of the
  providers. They are busy. If a command answers `rate_limited`, wait a
  moment and try again, or set a key of your own.
- The tool only calls the data routes of the providers. It never opens a
  browser and it never reads a web page.
- The messages of the providers are not shown in the interface, because
  they can be in Chinese. The tool says what happened in English.

---

## Development

Run the tests:

```bash
pip install -e ".[dev]"
python -m pytest tests/ -q
```

Every test is offline. The tests read the recorded answers in
`tests/fixtures/`, so they never touch the network.

Run the smoke script to check the live providers:

```bash
python tools/smoke.py
```

The script calls every provider once and prints one status line for each
of them. It sleeps between the calls on purpose, because the shared keys
belong to live websites.

---

## Project layout

```
mapquery/
├── pyproject.toml
├── README.md
├── README.zh-CN.md                # the Chinese readme
├── docs/
│   ├── PLAN.md                     # the plan of the version
│   └── DATA_SOURCES.md             # the traced routes, with raw samples
├── src/mapquery/
│   ├── __init__.py                 # the version
│   ├── __main__.py                 # python -m mapquery
│   ├── cli.py                      # the commands and the options
│   ├── config.py                   # the keys, from the environment and the file
│   ├── models.py                   # Place, Route, GeoResult, ProviderResult
│   ├── coords.py                   # wgs84, gcj02 and bd09
│   ├── mercator.py                 # the Baidu Mercator metres
│   ├── http.py                     # the session, the retries and the rate limits
│   ├── cache.py                    # the small disk cache
│   ├── engine.py                   # the thread pool and the fan out
│   ├── compare.py                  # the clusters, the consensus and the spread
│   ├── filters.py                  # the filter on the types of the places
│   ├── render.py                   # the table, the JSON and the CSV
│   └── providers/
│       ├── __init__.py             # the registry
│       ├── base.py                 # the interface of every provider
│       ├── baidu.py                # both channels of Baidu
│       ├── amap.py                 # both channels of Amap
│       ├── tencent.py              # both channels of Tencent
│       └── direct_keys.py          # the keys of the direct channel
├── tools/
│   ├── trace_sources.py           # re-record the traced replies
│   ├── smoke.py                   # one live call per provider
│   └── check_readmes.py           # check that the two readmes agree
└── tests/
    ├── conftest.py
    ├── fixtures/                   # the recorded real answers
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

## License

MIT.
