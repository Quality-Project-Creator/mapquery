# mapquery 对抗性代码审查（v0.0.1）

- 审查对象：`src/mapquery/**`（全部 13 个模块，含代码实现角色新增的 `filters.py`）
- 基线 commit：`6433862ac7`（`mqpush.py --sync` 后）
- 复核：代码实现角色在 `a97111516c` 之后改动了 `src/**`（新增 `filters.py`、类型过滤功能、可配置的聚类半径）。本文件的所有行号与结论都**对 `6433862ac7` 重新核对过**，三条 xfail 缺口在该版本上依然成立。
- 审查角色：测试验证（jade）
- 复现环境：Windows 10.0.26200 x64，Python 3.13（`E:\pro\mapquery\.venv`）
- 审查方式：逐行读源码 + 针对性探针脚本实测 + 为每条结论写回归测试
- 本文件只描述问题与建议，**不改动 `src/**`**（实现归代码实现角色）

---

## 结论摘要

| 严重级 | 数量 | 编号 |
|---|---|---|
| 阻断 | 1 | R-01 |
| 高 | 3 | R-02, R-03, R-04 |
| 中 | 7 | R-05, R-06, R-07, R-08, R-09, R-10, R-11 |
| 低 | 5 | R-12, R-13, R-14, R-15, R-16 |

本轮重点核查的五个方向里，**经纬度顺序、bd09/gcj02 互转精度、每 provider 的令牌桶限流、重试、密钥不进日志也不进磁盘缓存，这五项实现是正确的**（详见文末"已验证有效"）。问题集中在**错误路径的状态失真**和**跨平台权限**两块。

---

## 阻断

### R-01 百度直连通道的网页兜底会把"被限流"变成"ok 但没有数据"

- **文件:行**：`src/mapquery/providers/baidu.py:118`（`_search_direct` 的 `except ProviderError:`）；同样的写法在 `baidu.py:317`（`_geocode_direct`）和 `baidu.py:428`（`_reverse_direct`）
- **问题**：`_search_api` 抛出的**任何** `ProviderError`（包括 `ProviderStatus.RATE_LIMITED`）都被 `except ProviderError:` 吞掉，然后转去请求网页兜底路由。网页兜底返回一个结构合法但内容为空的 body（如 `{"content": [], "result": {}}`），`parse_search_places` 于是返回 `[]`，调用方看到的是 `status=ok`、`data=[]`。
- **为什么是问题**：状态行会显示 `baidu: ok`，但实际上百度限流了我们。这直接违背了工具自己在 `src/mapquery/cli.py:891-892` 写下的承诺——"A provider that fails keeps its own status. It is never reported as an answer with no data."。后果有三个：
  1. compare 命令无法区分"三家都没搜到"和"百度被限流"，聚类结果和 spread 统计因此失真；
  2. 用户看不出该等一会儿重试，还是该换个关键词；
  3. `_cmd_matrix` 那句"失败 provider 保留自己的状态"的逻辑，在百度这条路径上不成立。
- **复现**：
  ```python
  # 官方 API 抛 RATE_LIMITED，网页兜底返回空 body
  provider.search_places("天安门")   # -> []，没有异常，状态被当成 ok
  ```
  回归测试已写好：`tests/test_providers.py::test_a_rate_limited_baidu_search_is_not_muted_by_the_web_fallback`（当前标记为 xfail）。
- **建议修法**：兜底只应该用于"官方 API 拒绝了但服务本身可用"的情况。建议给 `ProviderError` 增加一个 `fallback_allowed` 标志（或按状态白名单：只有 `ERROR` 且错误码不是限流/超时才允许兜底），限流、超时、服务端错误一律直接向上抛，保留原状态。
- **严重级**：阻断

---

## 高

### R-02 百度 POI 的坐标读不出来时会变成 (0,0)

- **文件:行**：`src/mapquery/providers/baidu.py:246`、`baidu.py:254-255`（`_mercator_of`），根因在 `src/mapquery/providers/base.py:236`（`_as_float` 的默认值是 `0.0`）
- **问题**：`_mercator_of` 只检查 `x`/`y` 是否为 `None`，**不检查能否解析成数字**。`_as_float("abc")` 返回默认值 `0.0`，于是 `mc_to_ll(0.0, 0.0)` 得到 `(2.89e-09, -3.07e-08)`，再经 `bd09_to_gcj02` 得到约 `(-0.0065, -0.0060)`——几内亚湾里的一个点。
- **为什么是问题**：工具把一个坏掉的 POI 当成真实地点报出来，还带着名字和地址。compare 会把它当成正常的一个点参与聚类；只要三家中有一家返回这种坏数据，就会凭空造出一个"共识簇"，而 spread 统计也会被拉到地球另一端。这是**静默返回错误数据**，比返回空结果更糟。
- **复现**：
  ```python
  provider.parse_search_places({"content": [{"name": "x", "x": "abc", "y": "abc"}]})
  # -> 1 个地点，坐标 (-0.0065, -0.0060)
  ```
- **建议修法**：在 `_mercator_of` 里用严格解析（失败返回 `None`），让 `_place_from_entry` 返回 `None` 从而跳过这条记录；或者至少校验范围 `0 < |x| < 2e7`、`0 < |y| < 2e7`。
- **回归测试**：`tests/test_providers.py::test_a_broken_baidu_position_is_not_a_place_at_zero`（当前 xfail，修好即可去掉标记）
- **严重级**：高

### R-03 Windows 上存放 API key 的配置文件没有真正的权限保护

- **文件:行**：`src/mapquery/cli.py:1708-1717`（`_write_private_file`）
- **问题**：函数用 `os.open(path, ..., 0o600)` 建文件，并调用 `os.chmod(path, 0o600)`。**在 Windows 上 `os.chmod` 只会增删"只读"属性**，而 0o600 里带写权限，所以这次调用等于什么都没做，文件保留所在目录的 NTFS DACL。
  实测本机默认配置目录的 DACL：

  ```
  C:\Users\Administrator\.config
      NT AUTHORITY\Authenticated Users:(I)(M)
      BUILTIN\Users:(I)(RX)
  ```

  也就是说，**本机任何一个普通用户都能读（甚至改写）`~/.config/mapquery/config.toml` 里的百度/高德/腾讯 key**。
- **为什么是问题**：这个文件里放的就是用户自己申请的付费配额凭据。POSIX 上 0o600 真的挡住了其他用户，Windows 上没有，两个平台行为不一致；而 `config init` / `config set` 的文档和 README 都让人以为这个文件是私密的。共享机器、域环境、有人拿到过备份的场景下，这是凭据泄露。
- **建议修法**：在 `_write_private_file` 里按平台分支。Windows 上用 `icacls <file> /inheritance:r /grant:r "<当前用户>":(F)`（或用 ctypes 调 `SetNamedSecurityInfo`）把 DACL 换成只有属主；建目录时同样处理 `~/.config/mapquery`。POSIX 保持 0o600，目录用 0o700。
- **回归测试**：`tests/test_cli.py::test_the_config_file_is_only_readable_by_the_user` 已经会用 `icacls` 读真实 DACL 来判定，修好之后 Windows 分支在普通临时目录里也会真正通过而不是 skip
- **严重级**：高（共享机器上等同阻断）

### R-04 "没有数据"和"所有 provider 都成功但结果为空"在退出码上分不开

- **文件:行**：`src/mapquery/cli.py:723`（`_exit_code`）、`src/mapquery/cli.py:738-764`（`_finish`），对照 `README.md:451-457`
- **问题**：`_exit_code` 只要有任意一个 provider 的 status 是 `OK` 就返回 0。而 `_finish` 里那句 `"No provider could answer with data."`（`cli.py:764`）只在 `not rows and not all(result.is_ok ...)` 时才打印——也就是**"所有 provider 都失败"**才打印。如果 provider 都成功但没找到地方（`data=[]`），表格是空的，屏幕上没有任何说明，退出码却是 0。
- **为什么是问题**：README 明确写着 `0 | At least one provider answered with data`。现在"一个都没搜到但大家都很开心地返回了空"也给 0，靠退出码判断成败的脚本会把"没搜到"当成"搜到了"。`_cmd_weather` 有同样的问题：Amap 返回 ok 但 body 里没有 `lives`/`forecast` 时，同样是空表 + 退出码 0。

  **实现自己前后也不一致（`6433862ac7` 实测）**：代码实现角色新增的类型过滤走的是另一条退出码规则——`cli.py:849` 和 `cli.py:1259` 用 `_exit_code_of_types(places)`（`cli.py:588`），它的规则是"没有一个地点活下来就返回 1"。同一个 provider 答出 0 个地点时：

  - `mapq search x` → 退出码 **0**
  - `mapq search x --types 博物馆` → 退出码 **1**

  同一种情况，只因为多写了一个选项，退出码就变了。这让 R-04 从"文档与实现不一致"升级成"实现内部前后不一致"。
- **建议修法**：三处说法必须统一（普通命令、`--types` 命令、README）。二选一——(a) 把 `_exit_code` 改成"至少一个 provider 答出数据"（有行才算数）；(b) 保持现在的退出码，但把 README 里 0 的定义改成"至少一个 provider 成功应答"，同时让 `_finish` 在"都成功但没有行"时打印一行明确说明。倾向 (b) 更保守（"搜索成功但没结果"退出码 0 是常见约定），但一定要改一处，不能两处不一致。
- **严重级**：高

---

## 中

### R-05 畸形的回复被读成"成功但没有数据"

- **文件:行**：`src/mapquery/providers/tencent.py:109`（`parse_search`）、`src/mapquery/providers/tencent.py:325`（`_check_status`）、`src/mapquery/providers/amap.py:133`（`parse_search`）
- **问题**：腾讯和高德的 `parse_search` 在 body 不是对象、或 `data`/`pois` 不是 list 时一律 `return []`。腾讯的 `_check_status` 里 `status` 不存在时直接 return，等于把一个坏掉的 body 当成成功。
- **为什么是问题**：这正是"静默返回空结果冒充没有数据"那一类问题。要区分两件事：provider 明确说"没有这个地点"是正常业务结果（body 里有明确的空数组），而"回复结构不对"是故障。现在两者无法区分，叠加 R-04 之后用户屏幕上就是一张空表 + 退出码 0。
- **建议修法**：`parse_search` 在 body 不是 dict、或 `data`/`pois` 缺失或类型不对时，抛 `ProviderError(..., ProviderStatus.ERROR)`；"provider 确实没有数据"只走 body 里明确的空数组那条路。
- **回归测试**：`tests/test_providers.py::test_a_tencent_reply_without_data_is_an_error`（当前 xfail）
- **严重级**：中

### R-06 空结果会被写进磁盘缓存并回放一小时

- **文件:行**：`src/mapquery/http.py:92`（`is_good_body`）
- **问题**：`is_good_body` 的文档字符串写着"A reply that says the call worked but holds nothing is not kept either"，但这段逻辑**只对高德 v3 的字符串 `"1"` 生效**。百度和腾讯用数字 status，走到 `if isinstance(status, int): return status == 0` 就直接返回 True，于是 `{"status": 0, "data": []}` 会被缓存。
- **为什么是问题**：provider 这一分钟返回空（限流边缘、风控、刚改过数据），工具会把这个"空"当正常答案缓存一小时，之后同一个查询一直返回空，而用户看到的还是 `ok` + `from the cache`，完全看不出异常。
- **建议修法**：把"有数据"的要求提到 status 判断之前，对三家统一：status 0/1 之后还要检查 body 里至少有一个非空的业务列表（`pois`/`geocodes`/`results`/`data`/`routes`/`districts`/`lives`/`forecast`/`regeocode`）。注意 `tests/test_http.py::test_a_good_body_is_recognised` 里 `is_good_body({"status": 0}) is True` 和 `is_good_body({"results": []}) is True` 两条断言要一起改。
- **严重级**：中

### R-07 `ll_to_mc` 在南半球选错了插值带

- **文件:行**：`src/mapquery/mercator.py:73`
- **问题**：`row = next((i for i, band in enumerate(LLBAND) if lat >= band), len(LLBAND) - 1)` 用的是 `lat >= band`，而百度参考实现是 `Math.abs(x) >= LLBAND[i]`。南纬的 lat 永远小于 0，所以永远落到兜底的第 5 带。
- **为什么是问题**：实测 `lat=-30` 时 Python 选带 5、参考实现选带 3，y 差约 **133 米**（-3481856.8 对 -3481989.9）；`lat=-45` 差约 900 米。北半球完全正确，所以现有测试没发现。模块文档里"verified to better than one centimetre on a round trip"只覆盖了北京/深圳/上海/乌鲁木齐这四个北半球城市。
- **建议修法**：改成 `abs(lat) >= band`。同时给 `ll_to_mc`/`mc_to_ll` 补一组南半球往返测试（当前 `tests/test_mercator.py` 只测北半球）。现在 `ll_to_mc` 只被测试用到，暂无用户可见影响，但这是个埋着的雷。
- **严重级**：中

### R-08 配置里把某个 provider 的速率写成 0，会静默关掉这个 provider 的限流

- **文件:行**：`src/mapquery/config.py:308-311`、`src/mapquery/http.py:227`
- **问题**：`Config.load()` 用 `_as_float(value, limits.get(str(name), 0.0))` 读 `rate_limits` 表；`RateLimiter.acquire()` 开头是 `if self.rate_per_second <= 0: return`，直接放行。
- **为什么是问题**：实测 `rate_limits = { amap = 0 }` 会让 amap 的限流**完全失效**（50 次 acquire 用了 0.0 秒）。用户本意多半是"限得更狠"，结果反而变成"完全不限"，直接把自己打进服务商的限流黑名单，而且没有任何提示。同理，`rate_limits` 表里一个拼错的 provider 名会拿到 0.0，也会变成不限流。
- **建议修法**：读配置时把 <= 0 的值当作错误处理（回退到默认值并打一条 warning），或最小值钳到 0.1；同时在 `config show` 里把**生效中**的速率显示出来。
- **严重级**：中

### R-09 一个 provider 的请求状态会被它的最后一次请求覆盖

- **文件:行**：`src/mapquery/http.py:323`（`_remember`）、`src/mapquery/cli.py:692`（`_add_http_state`）
- **问题**：`_state[provider]` 每发一个请求就被整个覆盖。matrix 命令要给同一个 provider 连续地理编码多个地址，这时 provider 的 `attempts` / `quota` / `cached` 都只剩**最后一个**请求的。
- **为什么是问题**：状态行和 verbose 输出会低报重试次数（真实重试 3 次只显示 1 次），`cached` 标志也可能说反（前面几个地址是缓存的、最后一个是网络请求，结果只显示最后那个）。这直接影响用户判断"是不是被限流了"。
- **建议修法**：`_state` 改成按 provider 累加（attempts 求和、cached 取"全部命中"），或在 `_call_providers` 里按请求粒度保存。
- **严重级**：中

### R-10 Python 3.9 上同一个配置文件会被判为坏文件

- **文件:行**：`src/mapquery/config.py:116`（`_load_simple_toml`）
- **问题**：项目声明支持 Python 3.9+，但 3.9 没有标准库 `tomllib`，只能走这个简易 TOML 读取器。它不支持行尾注释：`key = "abc"  # 注释` 会被当成"引号没有闭合"，抛 `ConfigFileError`。
- **为什么是问题**：实测同一个文件，标准库 `tomllib` 读出来是 `{'amap': {'key': 'abc', 'jobs': 8}}`，简易读取器直接抛 `ConfigFileError`。用户 3.11 上好好的配置，换到 3.9 就变成"坏文件被忽略"，所有 key 静默丢失（`config.py` 的 `_load_toml` 只打一条 warning 就继续）。**同一个配置文件在两个受支持的 Python 版本上行为不同**。
- **建议修法**：把 `tomli` 加进 `pyproject.toml` 的依赖（3.9 有 wheels），或者给简易读取器补上行尾注释、内联表、数组的支持。推荐前者，改动最小。
- **严重级**：中

### R-11 坐标系转换对国界外的处理前后不一致

- **文件:行**：`src/mapquery/coords.py`（`wgs84_to_gcj02` 有 `is_outside_china` 判断，`gcj02_to_bd09` / `bd09_to_gcj02` 没有）
- **问题**：国界外的点，WGS-84→GCJ-02 不动，GCJ-02→BD-09 却照样加 0.0065 / 0.006 的偏移。
- **为什么是问题**：同一个国界外的点，转 GCJ-02 和转 BD-09 的位移量不一样，工具内部不自洽。虽然百度确实在整个中国范围用这一套偏移，但 `convert` 是公开 API（CLI 的 `mapq convert` 也直接暴露它），用户拿到一个东京的点再转 BD-09，会得到一个看起来很精确、其实只是加过偏移的坐标。
- **建议修法**：要么在文档里写清楚"BD-09 偏移不判断国界"，要么在两个 bd09 函数里也做判断、国界外原样返回。倾向后者——工具内部系统是 GCJ-02，国界外的点本来就不该被 BD-09 污染。
- **严重级**：中

---

## 低

### R-12 缓存里的"密文字段名"是写死的黑名单

- **文件:行**：`src/mapquery/cache.py:28`（`SECRET_FIELDS`）
- **问题**：只列了 key / ak / sk / sig / signature / secret / token / appkey / appsecret / password。
- **为什么是问题**：现在三个 provider 的回复都不带 key，所以现状没问题。但只要 provider 哪天把 key 放在叫 `apiKey` / `api_key` / `access_token` / `secret_key` / `keyid` 的字段里回显，它就会原样写进 `~/.cache/mapquery`。黑名单永远追不上字段名的变化。
- **建议修法**：在黑名单之外再加一道"值等于本次请求用到的 key"的兜底比对（把 key 值传进 scrub，命中就替换成 masked）；或者改成白名单，只保留已知安全的业务字段。
- **严重级**：低

### R-13 配置目录和缓存目录用的是默认权限

- **文件:行**：`src/mapquery/cli.py:1729`（`os.makedirs(folder, exist_ok=True)`）、`src/mapquery/cache.py:164`
- **问题**：两个目录都用默认的 `0o777 & ~umask`（一般是 0o755）创建。
- **为什么是问题**：配置文件本身是 0o600，key 读不到；但其他用户能列出目录、知道里面有哪些文件。缓存目录里是各家的查询结果（POI、地址等），也算用户数据。
- **建议修法**：创建目录时显式给 0o700（POSIX）；Windows 上跟 R-03 一起处理。
- **严重级**：低

### R-14 高德的 location 串超过两段时，多出来的部分被悄悄丢掉

- **文件:行**：`src/mapquery/providers/amap.py:616`（`_split_location`）
- **问题**：`value.split(",")` 之后只取前两个，没有检查长度。
- **为什么是问题**：`"116.397,39.908,extra"` 会得到 `(116.397, 39.908)`，看起来完全正常，实际第三个分量被丢了。真实的高德回复不会这样，但代理层或将来的字段变化可能带来这种形状。
- **建议修法**：`len(parts) != 2` 时返回 None。
- **严重级**：低

### R-15 `--timeout 0` 会绕过工具自己的错误提示

- **文件:行**：`src/mapquery/http.py`（`request_json` 里 `request_timeout = (self.connect_timeout, read_timeout)`）
- **问题**：requests 对 <= 0 的 timeout 抛的是普通 `ValueError`（实测 `Invalid timeout (3.1, 0.0)...`），**不是** `requests.RequestException`，所以 `except requests.RequestException` 抓不到。
- **为什么是问题**：用户看到的不是工具那句清楚的英文错误，而是 requests 的原始 ValueError，状态行里也会变成一条看不懂的 error。`--timeout 0` / `--timeout -1` 应该在参数校验阶段就被拒绝。
- **建议修法**：在 `Settings.__init__` 里校验 `timeout > 0`，否则抛 `UsageError`（退出码 2）。
- **严重级**：低

### R-16 直连通道用的是三家自己前端 bundle 里的公共 key

- **文件:行**：`src/mapquery/providers/direct_keys.py:11-25`
- **问题**：三个前端 key 硬编码在源码里。
- **为什么是问题**：这是百度/高德/腾讯自己放在公开 bundle 里的 key，本来就是公开的，但所有 mapquery 用户共用同一份配额，provider 端一旦收紧就大家一起降速；而且这些 key 会跟着版本一直留在 git 历史里。
- **建议修法**：短期在 README 里更醒目地写清"直连通道共用的是公共配额，可能随时失效"；长期把直连通道定位成"没有 key 时的应急通道"，官方通道作为推荐路径。
- **严重级**：低

---

## 已验证有效（这五项实现是对的，且已补回归测试）

这几条是本次专门去查的方向，结论是**实现没有问题**，并已用测试钉住：

1. **经纬度顺序全部正确。** 逐个核对了每个 provider 的每一处请求参数与回复解析：
   - 百度：`location` / `origin` / `destination` 用 `lat,lng`（百度文档即 `lat,lng`）；回复 `location` 是 `{lng, lat}`；百度 route 的 `polyline` 是 `[lng, lat]`。
   - 高德：`location` / `origin` / `destination` 用 `lng,lat`；回复 `location` 是 `"lng,lat"` 字符串；polyline 是 `lng,lat`。
   - 腾讯：`from` / `to` / `location` 用 `lat,lng`；回复 `location` 是 `{lng, lat}`；polyline 是 `lat,lng`（`_parse_polyline(..., lat_first=True)`）。
   - Mercator：`mc_to_ll` 的带选择用 `abs(my)`，与百度参考实现一致。
   - 新增 `tests/test_coords.py` 的顺序测试把这一点钉住了（含"交换参数后经纬度值对调"的断言）。

2. **bd09 / gcj02 互转是干净的。** 7 个城市（北上深、乌鲁木齐、拉萨、哈尔滨、三亚）实测：
   - GCJ-02→BD-09→GCJ-02 往返误差 **< 0.12 m**
   - GCJ-02→WGS-84→GCJ-02 往返误差 **< 0.01 m**
   - WGS-84→BD-09→WGS-84 全链往返误差 **< 0.5 m**
   - BD-09 偏移量 lng +0.0064~+0.0066、lat +0.0056~+0.0063，与文档一致。

3. **每 provider 的令牌桶限流是真的生效。** `HttpClient` 一个 run 只建一个、所有 provider 线程共用；`limiter(provider)` 每个 provider 一个桶且在锁下创建；每次**真实请求之前**都会 `acquire()`，**命中缓存则不消耗令牌**；重试也算一次请求，会重新取令牌。新增 `tests/test_http.py` 的并发测试证明：同一 provider 的 4 个线程会互相排队（>= 0.30 s），不同 provider 各有各的桶（一个把桶用光不影响另一个）。

4. **重试是真的重试。** 超时、连接断开、HTTP 429、HTTP 5xx、以及 body 里说"被限流"（腾讯 120、百度 4、高德 10003/10004/10009/10021/10029、v4 的 errcode）都会重试；次数是 `retries + 1`；重试之间是指数退避 + 抖动；429 优先用 `Retry-After` 头（上限 60 s）；400 这类用户错误不重试；耗尽重试后状态分别正确（rate_limited / error / timeout / error）。

5. **密钥不会进日志，也不会进磁盘缓存。** 错误信息一律用 `safe_url()` 去掉 query string；requests 的异常只用类名不用文本（文本里含完整 URL）；缓存文件名是请求参数的 SHA-256，密钥不在文件名里；缓存内容会被 `_scrub` 过一遍（字段名命中黑名单就丢掉，字符串里的 `?key=...` 替换成 masked）；`config show` / `providers` 只显示掩码后的 `...abcd`。唯一残留风险是 R-12。

6. **代码实现角色本轮新增的类型过滤（`src/mapquery/filters.py`）没有踩到同样的坑**：
   - `--types` 的空项由 `filters.parse_types` 抛 `ValueError`，`cli.py:485-488` 把它转成 `UsageError`，所以退出码是 2 而不是 traceback；
   - 配置里新增的 `cluster_radius` / `name_ratio` / `same_place_radius` 由 `cli.py:491-513` 的 `_number_of` 做区间检查（配置文件里的值和命令行选项走同一道检查），越界会得到 UsageError；
   - `filters.filter_places` 只做过滤，不改地点、不造地点，被丢掉的地点会报出数量。
7. **线程模型是干净的。** `HttpClient.session` 是 `threading.local`（一个线程一个 session）；`run_many` 用 `ThreadPoolExecutor`，结果按**输入顺序**返回而非完成顺序；一个 provider 抛异常不影响其他 provider；worker 数 = `min(jobs, provider 数)`；`jobs <= 0` 会被兜到 1。

---

## 本轮新增测试与问题的对应关系

| 问题 | 回归测试 | 状态 |
|---|---|---|
| R-01 限流被网页兜底吞掉 | `test_providers.py::test_a_rate_limited_baidu_search_is_not_muted_by_the_web_fallback` | xfail（待实现角色修） |
| R-02 坏坐标变成 (0,0) | `test_providers.py::test_a_broken_baidu_position_is_not_a_place_at_zero` | xfail（待实现角色修） |
| R-05 畸形回复当空结果 | `test_providers.py::test_a_tencent_reply_without_data_is_an_error` | xfail（待实现角色修） |
| R-03 Windows 权限 | `test_cli.py::test_the_config_file_is_only_readable_by_the_user` | 已通过（读真实 DACL，POSIX 断言原样保留） |
| R-04 退出码语义 | `test_cli.py::test_the_exit_codes_are_the_three_of_the_readme` | 已通过（钉住 0/1/2 三种情形） |
| 顺序 / 精度 / 国界 | `test_coords.py` 新增 23 个用例（10 → 33） | 已通过 |
| 限流 / 重试真实生效 | `test_http.py` 新增 8 个用例（35 → 43） | 已通过 |
| 畸形输入（各 provider 解析器） | `test_providers.py` 新增 23 个用例（45 → 68） | 已通过 |

xfail 用例用的是 pytest 默认的 `strict=False`：现在失败会被记成 xfailed（套件保持绿），**代码修好后会变成 xpassed**，届时去掉 `@pytest.mark.xfail` 即可转为正式断言。

### 用例总数变化

| 文件 | 上游 `6433862ac7` | 本轮改动后 | 变化 |
|---|---|---|---|
| `tests/test_cli.py` | 42 | 43 | +1（退出码语义；权限用例改写，不计新增） |
| `tests/test_coords.py` | 10 | 33 | +23 |
| `tests/test_http.py` | 35 | 43 | +8 |
| `tests/test_providers.py` | 45 | 68 | +23 |
| **合计** | **228** | **283**（280 passed + 3 xfailed） | **+55** |

上游基线在本轮开始时是 `a97111516c`（217 个用例，Windows 上挂 1 个）。代码实现角色随后把上游推到 `6433862ac7`（228 个用例），本轮在它之上继续做。基线那条失败用例（`test_the_config_file_is_only_readable_by_the_user`）已修好，且 POSIX 的原断言原样保留。
