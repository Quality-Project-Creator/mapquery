# mapquery（中文版）

> 英文版：[README.md](README.md)。本文是它的中文翻译，内容与英文版一致。
> 源码、命令行输出和文档仍以英文为准。

`mapquery` 同时向百度地图、高德地图、腾讯地图问同一个问题。
它把三份结构不同的答案归一成同一种格式，并排放在一起。
然后告诉你各家在哪里一致、在哪里不一致。

**开箱即用，不需要任何 API Key。**

---

## 安装

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

装完之后就可以使用 `mapq` 命令。

也可以不安装直接运行：

```bash
PYTHONPATH=src python -m mapquery --version
```

工具需要 Python 3.9 或更高版本。只依赖 `requests` 和 `rich` 两个库。

---

## 快速上手

三条命令，以及它们真实打印出来的内容。

### 1. 搜索地点

```bash
mapq search 天安门 --city 北京 --limit 3
```

```
baidu: ok (direct, 379 ms) | amap: not_configured (no AMAP_API_KEY) | tencent: ok (direct, 284 ms)

 provider ┃ name            ┃ address                                  ┃ category              ┃        lng ┃       lat
━━━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━
 baidu    │ 天安门          │ 北京市东城区长安街                       │ 旅游景点;文物古迹     │  116.39759 │ 39.908776
 baidu    │ 天安门广场      │ 北京市东城区东长安街                     │ 旅游景点;文物古迹     │ 116.397799 │ 39.903307
 baidu    │ 天安门东        │ 地铁1号线八通线                          │ 交通设施;地铁站       │  116.40154 │ 39.907736
 tencent  │ 天安门          │ 北京市东城区东华门街道西长安街           │ 旅游景点:国家级景点   │  116.39747 │ 39.908823
 tencent  │ 天安门广场      │ 北京市东城区东长安街                     │ 旅游景点:风景名胜     │ 116.397827 │  39.90374
 tencent  │ 天安门广场-国旗 │ 北京市东城区东长安街与广场东侧路交叉口西 │ 旅游景点:其它旅游景点 │  116.39757 │  39.90693
```

第一行是每个服务商的态。它说明谁答了、走的是哪条通道、用了多久。

### 2. 比较各家答案

```bash
mapq compare 天安门 --city 北京 --limit 5
```

```
baidu: ok (direct, 405 ms) | amap: not_configured (no AMAP_API_KEY) | tencent: ok (direct, 6 ms)

                                        Clusters
 id ┃ name            ┃ providers      ┃ members ┃        lng ┃       lat ┃ spread_max_m
━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━
  1 │ 天安门          │ baidu, tencent │       3 │ 116.397545 │ 39.908781 │         12.5
  2 │ 天安门广场      │ baidu, tencent │       2 │ 116.397813 │ 39.903523 │         48.2
  3 │ 天安门东        │ baidu, tencent │       2 │ 116.401407 │ 39.907755 │         23.1
  4 │ 天安门西        │ baidu          │       1 │ 116.391652 │ 39.907463 │          0.0
  5 │ 天安门广场-国旗 │ tencent        │       1 │  116.39757 │  39.90693 │          0.0
  6 │ 天安门广场-入口 │ tencent        │       1 │ 116.399506 │ 39.900906 │          0.0

                    Consensus
 id ┃ name       ┃ providers      ┃ spread_max_m
━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━
  1 │ 天安门     │ baidu, tencent │         12.5
  2 │ 天安门广场 │ baidu, tencent │         48.2
  3 │ 天安门东   │ baidu, tencent │         23.1

Spread: 3 clusters with more than one place, max 48.2 m, mean 27.9 m

Skipped:
  amap: Amap (Gaode) needs the key AMAP_API_KEY for search
```

### 3. 换算坐标

```bash
mapq convert --from bd09 --to gcj02 116.403963,39.915119
```

```
 from_system ┃ to_system ┃         lng ┃        lat
━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━
 bd09        │ gcj02     │ 116.3975904 │ 39.9087759
```

---

## 三家服务商

| 名称 | 服务商 | 官网 |
|---|---|---|
| `baidu` | 百度地图 | https://map.baidu.com |
| `amap` | 高德地图 | https://www.amap.com |
| `tencent` | 腾讯地图 | https://map.qq.com |

每家都有两条通道。

### 直连通道（direct）

直连通道是默认通道。不需要账号，不需要 Key。
它调用的是服务商自己网站在用的数据接口。
那些接口里带着发布在公开前端代码包里的 Key。

这些 Key 是和成千上万用户共用的，带来两个结果：

- 接口快、免费，装完立刻能用。
- 接口有速率限制。碰上繁忙的一分钟，你拿到的是 `rate_limited`，而不是数据。工具会如实告诉你，绝不会把限流伪装成"没有结果"。

百度的直连通道用官方 WebService API 加上百度前端代码包里的 AK；`map.baidu.com` 的网页接口作为备份。腾讯的直连通道用 `apis.map.qq.com` 的 WebService API 加前端 Key。高德的直连通道用 `www.amap.com` 的服务接口。

### 官方通道（official）

官方通道是服务商公开文档里的 WebService API，需要你自己的 Key。
在服务商官网免费申请，大约一分钟就能拿到。

把 Key 放进环境变量，这家就切到官方通道了。官方通道配额更好、不与任何人共享，而且功能更全：

| 服务商 | 环境变量 | 可选 |
|---|---|---|
| Baidu | `BAIDU_MAP_AK` | `BAIDU_MAP_SK` |
| Amap | `AMAP_API_KEY` | `AMAP_SECRET_KEY` |
| Tencent | `TENCENT_MAP_KEY` | `TENCENT_MAP_SK` |

```bash
export AMAP_API_KEY="your key here"
mapq providers
```

`providers` 命令会显示每家用的哪条通道、能做什么。Key 永远不会被完整打印，你只会看到末四位，例如 `...f3a9`。

也可以把 Key 放在文件里：

```bash
mapq config init          # 写入 ~/.config/mapquery/config.toml
mapq config set amap key "your key here"
mapq config show          # 显示配置，Key 会被遮蔽
```

新建的配置文件里带着工具的默认设置：

```toml
timeout = 10
connect_timeout = 3.1
retries = 2
jobs = 8
```

`connect_timeout` 是等连接的时间，`timeout` 是等回答的时间。

环境变量永远优先于配置文件。

配置文件只对你的用户可读，因为它存着 Key。无法解析的配置文件绝不会被使用，也绝不会被覆盖：工具会指出是哪个文件、说明它被忽略，然后继续用环境变量正常工作。

---

## 命令

### `mapq search <keyword>`

搜索地点。

```bash
mapq search 天安门 --city 北京 --limit 3
```

可选参数：`--city`、`--near lng,lat`、`--radius M`、`--limit N`。

带上 `--near` 时，工具还会显示到该点的距离。百度和腾讯的直连通道不支持周边检索，所以这两家会报 `not_supported`，其他服务商照常返回。

空关键词、空地址、空 `--city`、空 `--providers` 都是用法错误。工具会在调用任何服务商之前就以退出码 2 停下，并说明哪里不对。

### `mapq geocode <address>`

把地址转成坐标。

```bash
mapq geocode 天安门广场 --city 北京
```

```
baidu: ok (direct, 207 ms) | amap: ok (direct, 193 ms) | tencent: rate_limited (the rate limit was hit)

 provider ┃ address                ┃        lng ┃        lat ┃ level
━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━
 baidu    │ -                      │   116.3978 │ 39.903307 │ 旅游景点
 amap     │ 北京市东城区天安门广场 │ 116.397755 │ 39.903182 │ 兴趣点
```

### `mapq reverse <lng,lat>`

把坐标转成地址。坐标写作 `lng,lat`。

```bash
mapq reverse 116.3975904,39.9087759
```

```
baidu: ok (direct, 123 ms) | amap: not_configured (no AMAP_API_KEY) | tencent: ok (direct, 153 ms)

 provider ┃ address                            ┃        lng ┃       lat ┃ level
━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━
 baidu    │ 北京市东城区东华门街道中华路甲10号 │ 116.397591 │ 39.908776 │ 东城区
 tencent  │ 北京市东城区西长安街               │  116.39759 │ 39.908776 │ -
```

不是 `lng,lat` 格式的坐标属于用法错误。工具会以退出码 2 停下，并说明正确的格式。

### `mapq route <from> <to>`

找两个地点之间的路线。两端可以是 `lng,lat`，也可以是文字地址。文字地址先用同一个服务商做地理编码。

```bash
mapq route 天安门 116.39667,39.90864 --mode driving
```

```
baidu: not_supported (the channel cannot do this) | amap: ok (direct, 381 ms) | tencent: rate_limited (Tencent Maps could not find the start point: the provider rate limit was hit for https://apis.map.qq.com/ws/geocoder/v1/)

 provider ┃ mode    ┃ distance_m ┃ distance_km ┃ duration_min
━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━
 amap     │ driving │     1026.0 │       1.026 │          9.1

Steps:
  amap (driving):
    1. 向北行驶396米左转 (396 m)
    2. 沿东华门路向西行驶101米左转 (101 m)
    3. 向南行驶157米向左前方行驶 (157 m)
    4. 向东南行驶7米靠左 (7 m)
    5. 向东南行驶21米向右前方行驶 (21 m)
```

模式有：`driving`、`walking`、`cycling`、`transit`。每家对同一个模式叫法不同，所以 `cycling` 在高德和腾讯那边叫 `bicycling`。做不到某个模式的服务商会直说。

百度的路线需要你自己的 Key。共享的那个 AK 上路线服务是关掉的，所以百度的直连通道报 `not_supported`。百度本身没有步行、骑行、公交路线，所以这些模式在任何通道上都报 `not_supported`。

### `mapq matrix --from "a;b" --to "c;d"`

多个点之间的直线距离。点可以是 `lng,lat`，也可以是地址。距离在你本机算。

```bash
mapq matrix --from "116.397428,39.908823;天安门" --to "116.39667,39.90864;天安门广场"
```

```
baidu: ok (direct, 11 ms) | amap: ok (direct, 9 ms) | tencent: ok (direct, 3604 ms)

  Straight line distance in metres. This is not a road
                       distance.
 from                 ┃ 116.39667,39.90864 ┃ 天安门广场
━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━
 116.397428,39.908823 │               67.8 │      614.2
 天安门               │               79.9 │      608.4
```

这是直线距离，不是道路距离，也不是步行距离。

矩阵里的地址会用真正答得出来的那个服务商做地理编码。各家依次尝试，所以某个被限流的服务商不会拖累其他家。状态行会列出所有被问到的服务商和各自的状态。当没有一家能解析出地点时，命令会说明并以退出码 1 结束。这和"所有服务商都失败"是同一个退出码，含义是：没有任何一家给出了数据。

### `mapq compare <keyword>`

核心功能。它问遍所有服务商，把指向同一个地点的答案归成一组，并测量各家之间的差距。数字的含义见[下一节](#compare-功能)。

```bash
mapq compare 天安门 --city 北京 --limit 5
```

可选参数：`--city`、`--near lng,lat`、`--radius M`、`--limit N`。

### `mapq convert --from <system> --to <system> <lng,lat>`

把一个点从一种坐标系换到另一种。这一步是纯本地的，永远可用，从不联网。

```bash
mapq convert --from bd09 --to gcj02 116.403963,39.915119
```

坐标系：`wgs84`、`gcj02`、`bd09`。

### `mapq district <keyword>`

显示一个地点的行政区划。

```bash
mapq district 北京
```

### `mapq weather <adcode>`

显示某个区域编码的天气。只有高德能做这件事。

```bash
mapq weather 110101
```

天气永远由高德提供。如果你用了 `--providers`，高德必须在列表里。否则命令会以退出码 2 停下，并说明选中的服务商都做不了天气。

如果高德没有配置，工具会说明情况并停下，不会影响其他工作。

### `mapq providers`

显示各服务商、将使用的通道、Key 状态和能力矩阵。

```bash
mapq providers
```

```
                                               Providers
 provider ┃ name         ┃ channel ┃ key     ┃ search ┃ geocode ┃ reverse ┃ route ┃ district ┃ weather
━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━
 baidu    │ Baidu Maps   │ direct  │ not set │ yes    │ yes     │ yes     │ no    │ no       │ no
 amap     │ Amap (Gaode) │ direct  │ not set │ no     │ yes     │ no      │ yes   │ no       │ no
 tencent  │ Tencent Maps │ direct  │ not set │ yes    │ yes     │ yes     │ yes   │ yes      │ no
```

### `mapq config show|set|init`

查看设置、管理 Key。参见[通道](#直连通道direct)。

---

## 输出格式

每个会和服务商打交道的命令都会打印一行状态：

```
baidu: ok (direct, 142 ms) | amap: not_configured (no AMAP_API_KEY)
```

这行永远都在，所以你随时知道谁答了。

来自本地缓存的回答会明确标出来：

```
tencent: ok (direct, cached, 3 ms)
```

缓存在 `~/.cache/mapquery`。可以用环境变量 `MAPQUERY_CACHE_DIR` 换到别处，或者用 `--no-cache` 关掉。

| 格式 | 参数 | 去哪里 |
|---|---|---|
| 表格 | `--table`（默认） | 状态行和表格都走标准输出。 |
| JSON | `--json` | 每个服务商的状态放在 `providers` 键下面。 |
| CSV | `--csv` | 数据行走标准输出。状态行走错误输出，文件保持干净。 |

```bash
mapq search 天安门 --city 北京 --json
mapq search 天安门 --city 北京 --csv > places.csv
```

JSON 输出里有每次调用的全部事实：状态、通道、耗时、尝试次数、`cached` 标志，以及回答里的配额响应头。

compare 命令的 CSV 输出先是地点，然后是分组，最后是共识。第一列写着 `[places]`、`[clusters]` 或 `[consensus]` 的行是分节标记，后面就是该节的内容。分组行和地点行用同样的列：服务商列放该组包含的服务商，坐标列放该组的中心，另外两列放地点数量和最大距离。

全局参数放在命令前后都可以：

```bash
mapq --json search 天安门
mapq search 天安门 --json
```

只能选一种格式。`--json` 和 `--csv` 同时使用会让命令以退出码 2 停下。

其他全局参数：

| 参数 | 含义 |
|---|---|
| `--providers baidu,amap` | 只调用这些服务商。空列表属于用法错误。 |
| `--jobs N` | 同时调用多少家服务商。默认 8。 |
| `--timeout S` | 单次请求的读超时秒数。默认 10。 |
| `--retries N` | 失败的请求重试几次。默认 2。 |
| `--no-cache` | 不使用本地缓存。 |
| `--verbose` | 打印更多过程信息。 |
| `--version` | 打印版本号。 |

verbose 模式会在状态行下面为每个服务商多打一行，包含通道、耗时、尝试次数、回答来自哪里，以及有的话给出配额响应头：

```
baidu: channel direct, 142 ms, 1 attempt(s), from the network
tencent: channel direct, 90 ms, 3 attempt(s), from the network, quota current_qps=3, limit_qps=500
```

### 退出码

| 退出码 | 含义 |
|---|---|
| 0 | 至少一家服务商给出了数据，或者矩阵算出来了。 |
| 1 | 没有任何一家给出数据：要么全都失败，要么矩阵解析不出地点。 |
| 2 | 命令用错了，比如坐标不合法或关键词为空。 |

---

## 坐标系

三家用了两种坐标系、两种坐标顺序：

| 服务商 | 坐标系 | 顺序 |
|---|---|---|
| Baidu | BD-09 | `lat,lng` |
| Amap | GCJ-02 | `lng,lat` |
| Tencent | GCJ-02 | `lat,lng` |

BD-09 是在 GCJ-02 之上再叠一层偏移。两者加起来能把一个点挪动几百米，足以毁掉一次比较。

工具内部只保留一种顺序和一种坐标系：顺序是 `lng,lat`，坐标系是 GCJ-02。每家服务商都在自己的边界上做换算，所以你永远看不到这团乱麻。

百度还有一点需要说明。百度的网页接口给地点位置时不给普通经纬度，给的是百度墨卡托米。工具自带这套换算，放在 `src/mapquery/mercator.py` 里，算出来的数与官方 API 能对到厘米级。

---

## compare 功能

`mapq compare` 是这个工具存在的理由。同一个问题，三个 API 用三种方式回答。拿到原始答案很容易，难的是判断它们说的是不是同一个地方。

工具分四步做这件事。

**1. 归一化名称。** 每个名称都转成 Unicode 的标准形式，去掉空格，字母转小写。所以 `"Tiananmen  Square"` 和 `"tiananmen square"` 是同一个名字。

名称匹配只在同一种文字系统内有效，跨不过去：`"Tiananmen Square"` 和 `"天安门广场"` 的名称相似度是 0.000，永远不会靠名字匹配上。用拉丁文搜中文名时，靠的是位置和 25 米规则，真正起作用的是位置规则。

**2. 匹配地点。** 不同服务商的两个地点是同一个地点，需要同时满足：

- 距离小于 150 米，并且
- 名字相似，相似度不低于 0.55。

距离小于 25 米的两个地点算同一个地点，哪怕名字不一样——那是同一栋楼。这条规则对任意两个地点都成立，不管来自哪家服务商，所以同一家服务商里相距 25 米的两个地点也算同一个。

**3. 建立分组。** 匹配上的地点被归到一起。一组里放的是同一个地点的全部答案。一组里可能包含同一家服务商的多个地点，因为一家服务商可能把同一个地方回答两次。

**4. 测量差距。** 每组会得到一个中心点（组内各点坐标的平均值），以及两个数字：

- `spread_max_m`：组内两点之间的最大距离。这是最坏情况。
- `spread_mean_m`：组内各点两两距离的平均值。这是常见情况。

分组是一条匹配链，所以一组的差距可能大于当初用来匹配的距离。`spread_max_m` 这一列才是该看的数字。

### 输出各部分的含义

| 名称 | 含义 |
|---|---|
| Places | 各家返回的地点行。 |
| Clusters | 指向同一个地点的地点分组。 |
| Consensus | 包含了所有"答了的"服务商的分组。 |
| Spread | 对所有多于一个地点的分组做的汇总：数量、最大差距、平均差距。 |
| Skipped | 没有作答的服务商，以及原因。 |

共识只针对真正作答的服务商来判定。如果高德搜不了，共识就只覆盖百度和腾讯。工具会告诉你高德被跳过了，以及为什么。

几米的差距是正常的。百度和腾讯都是 GCJ-02，本该很接近。50 米的差距意味着两家指的是略有不同的东西，比如城门和广场。

---

## 局限与实话

下面这些是在直连通道上、**不需要你自己的 Key** 就能用的：

| 功能 | Baidu | Amap | Tencent |
|---|---|---|---|
| POI 搜索 | 支持 | 需要 `AMAP_API_KEY` | 支持 |
| 地理编码 | 支持 | 支持 | 支持 |
| 逆地理编码 | 支持 | 需要 `AMAP_API_KEY` | 支持 |
| 驾车路线 | 需要 `BAIDU_MAP_AK` | 支持 | 支持 |
| 步行路线 | 不支持 | 需要 `AMAP_API_KEY` | 支持 |
| 骑行路线 | 不支持 | 需要 `AMAP_API_KEY` | 支持 |
| 公交路线 | 不支持 | 需要 `AMAP_API_KEY` | 支持 |
| 行政区划 | 不支持 | 需要 `AMAP_API_KEY` | 支持 |
| 天气 | 不支持 | 需要 `AMAP_API_KEY` | 不支持 |

"需要 Key"的意思是这个功能只在官方通道上有，所以你得配上那家的 Key。"不支持"的意思是这家根本没有这个功能。百度在这个工具里只有驾车路线。

高德的骑行路线在官方通道的 v4 接口上，腾讯的骑行路线在 `direction/v1/bicycling`。两家的模式名都叫 `bicycling`。

还有几条实话：

- 被限流的服务商报的是 `rate_limited`，这和"没有结果"不是一回事。工具绝不会把限流变成空答案。
- 做不到某个功能的服务商报 `not_supported`；做得到但没配 Key 的报 `not_configured`。
- 直连通道用的共享 Key 属于服务商的线上网站，它们很忙。如果命令返回 `rate_limited`，等一会儿再试，或者配一个自己的 Key。
- 工具只调用服务商的数据接口。它从不打开浏览器，也从不解析网页。
- 服务商返回的提示信息不会出现在界面上，因为那些信息可能是中文。工具用英文说明发生了什么。

---

## 开发

跑测试：

```bash
pip install -e ".[dev]"
python -m pytest tests/ -q
```

所有测试都是离线的。测试读取 `tests/fixtures/` 里录下的真实回答，所以从不碰网络。

用冒烟脚本检查线上服务商：

```bash
python tools/smoke.py
```

脚本会给每家服务商调一次，打印一行状态。它故意在调用之间 sleep，因为那些共享 Key 属于线上网站。

---

## 项目结构

```
mapquery/
├── pyproject.toml
├── README.md
├── README.zh-CN.md                 # this file, the Chinese readme
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
│   └── smoke.py                   # one live call per provider
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

## 许可证

MIT。
