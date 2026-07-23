# OKX K 线周期与连续性边界

`run_okx_research.py` 会把 `--bar` 传给 OKX `history-candles` 接口，并在任何回测或报告生成前按声明的周期验证时间序列连续性。本页记录当前代码实际支持的周期边界，避免把 OKX 接受但仓库尚不能安全验证的周期误当成可复现输入。

## 当前支持的固定宽度周期

连续性验证器当前覆盖以下区分大小写的单位：

- `s`：秒，例如 `1s`；
- `m`：分钟，例如 `1m`；
- `H`：小时，例如 `2H`；
- `D`：日，例如 `1D` 或 `3Dutc`；
- `W`：周，例如 `1W` 或 `1Wutc`。

可选的小写 `utc` 后缀改变 OKX candle 的 session anchor，不改变周期宽度。仓库回归测试明确覆盖 `1s`、`1m`、`2H`、`3Dutc` 和 `1Wutc` 的本地 cadence 映射。

这是仓库连续性验证器的支持边界，不代表 OKX 对每个品种都开放每个示例周期；交易所拒绝的 `bar` 仍会作为 OKX API 错误失败。周期标识区分大小写：`m` 表示分钟，而 `M` 表示日历月。研究命令应使用正整数数量和上述已验证单位。

## 当前会 fail closed 的周期

`1M`、`3Mutc` 等日历月周期长度随月份变化，不能用固定秒数验证连续性。未知格式也没有可审计的 cadence 语义。因此，当前下载器会在调用网络 getter 之前拒绝日历月和未知周期：

```text
ValueError: bar must be a supported fixed-width OKX interval; calendar and unknown intervals are rejected until calendar-aware continuity validation exists
```

不要通过删除该检查、把月线近似为固定天数，或在下载后静默补齐缺失 bar 来绕过边界。月线支持需要单独的日历步进、session anchor 和真实 OKX 月线 fixture 验证。

## 原始分页与下载后连续性检查

下载器在把页面内容加入规范化输入之前先验证 OKX 原始分页：

1. 每一页必须按时间戳严格从新到旧排列；乱序或同页重复时间戳会报 `must be strictly newest-to-oldest`；
2. 后续页面不能返回比当前 `after` 游标更新的行，否则报 `OKX pagination returned rows newer than the requested cursor`；
3. 精确重复的游标边界行可以跨页重叠，并计入 `duplicates_removed`；同一时间戳若字段内容冲突，则报 `conflicts with an earlier row for timestamp`；
4. 页面最早时间必须继续向过去推进，否则报 `OKX pagination did not move backward in time`。

这些分页检查发生在 `raw_rows` 接受页面、candle 归一化、回测和 artifact 持久化之前。下载器随后排除 `confirm != 1` 的未完成 candle，并应用 `start`/`end` 范围；精确跨页重叠只保留一条规范化记录。之后：

1. 每个相邻时间差必须是声明周期的整数倍；否则报 `off-cadence intervals`；
2. 整数倍大于 1 表示缺失一个或多个预期周期，下载器会报 `missing ... expected intervals`；
3. 指定 `--start` 时，只有 `max_pages` 用尽且最早返回 bar 仍晚于请求起点才会失败。若 OKX 先返回短页，或在已有数据后返回空页，下载器会保留可用历史，并分别记录 `pagination_termination=short_page` 或 `empty_page`；此时 `requested_start_reached` 可以为 `false`，例如品种上市晚于请求日期。

审计覆盖范围时必须同时检查 `pagination_termination` 与 `requested_start_reached`。成功完成下载并不等于请求起点一定已到达；若研究要求固定起始日期，应在下游门禁中显式拒绝 `requested_start_reached=false`，或先核实品种上市历史并调整研究起点。

## 显式结束边界由下载器强制，不是尽力而为过滤

任何直接调用 `fetch_okx_history_candles(..., end=...)` 的代码都会经过结束覆盖检查，而不只限于 `run_okx_research.py`。下载器会先把 `end` 规范到 UTC，并从已经验证的固定宽度 `bar` 推导 cadence；不可解析的结束时间或不支持的周期会在网络请求前失败。

下载器排除未完成 candle 并应用 `start`/`end` 范围后，要求：

- 最新完整 candle 不能晚于请求结束时间；否则报 `OKX download contains a completed candle after the requested end`；
- `end - latest` 必须严格小于一个声明周期。等于或超过一个完整周期表示结束边界缺少 candle，并报 `OKX download does not cover the requested end boundary`。

因此，最新 candle 恰好落在结束边界，或其时间戳与结束时间仍位于同一个固定宽度周期内时可以通过；缺少整个边界周期时，下载器不会返回可供直接调用者继续研究的 `OKXCandleSnapshot`。

canonical research CLI 还会在 `write_okx_snapshot()` 之前对返回快照做一层防御性复核。该层会明确拒绝不可解析的请求结束时间、缺失或非法的 `expected_step_seconds`、晚于请求结束时间的最新 candle，以及缺失整个结束周期的快照，错误分别包含 `requested end must be a valid timestamp`、`OKX snapshot is missing a valid expected bar cadence`、`OKX snapshot contains a completed candle after the requested end` 和 `OKX download does not cover the requested end boundary`。这层复核保护正式 artifact 写入边界；下载器层则保护所有直接调用者。

起点和终点语义并不对称：短页或空页可以使 `requested_start_reached=false` 的可用历史成功返回，但显式 `end` 是下载器级硬覆盖门禁。

## 省略结束边界时的实时新鲜度门禁

省略 `end` 且使用默认 live transport（没有注入 `get_json`）时，下载器不会再无条件接受任意陈旧的最后一根完整 candle。它会用 UTC 新鲜度参考时刻检查：

- 最新完整 candle 不能晚于参考时刻；否则报 `OKX download contains a completed candle after the freshness reference`；
- `freshness_age_seconds = reference - latest` 必须严格小于 `2 × expected_step_seconds + 5 分钟`；
- 等于或超过该阈值会报 `OKX open-ended download is stale`。

默认 `1Dutc` 的最大允许年龄因此是 `48 小时 5 分钟`。这个两周期容忍度允许当前 candle 尚未完成，同时仍要求返回最近的完整 candle。成功快照会记录 `freshness_checked_at_utc`、`freshness_age_seconds` 和 `freshness_max_age_seconds`，使 artifact 审计能够确认实际使用的门禁参数。

使用注入的 `get_json` 时，调用者必须显式传入 `as_of` 才会执行同一确定性检查；省略 `as_of` 会为 fixture 兼容而跳过新鲜度门禁，并把三个 metadata 字段记录为 `null`。反过来，默认网络 transport 不允许调用者传入 `as_of`，并会在网络请求前报 `as_of is only valid with an injected get_json`。

默认 live transport 会先完成网络分页、原始行解析、完整 candle 筛选和显式结束覆盖检查，然后在调用 `_validate_open_ended_freshness()` 之前立即采样当前 UTC。网络下载耗时因此已经计入 `freshness_age_seconds`，慢请求不能再依赖请求开始时的旧时钟通过门禁。注入 getter 的确定性路径不会读取墙上时钟，仍只使用调用者显式提供的 `as_of`。即便按下载完成时刻采样，这仍是容忍度门禁而非固定截止日期：需要字节级可复现时间边界的实验应保存并显式传入 `end`。

## 可执行自检

从已安装开发依赖的干净检出运行：

```bash
pytest \
  tests/test_okx_cadence.py \
  tests/test_okx_raw_page_integrity.py \
  tests/test_okx_end_coverage.py \
  tests/test_okx_open_ended_freshness.py \
  tests/test_run_okx_research_end_coverage.py \
  tests/test_okx_interval_documentation.py
```

这些测试使用仓库内真实 OKX fixture 的结构性副本验证：

- 已支持固定宽度标识的秒数映射；
- 日历月周期在网络请求前被拒绝；
- 均匀稀疏的 `1Dutc` 历史不能把两天间隔重新解释成完整日线；
- 原始页必须严格从新到旧，且后续页不能越过活动游标返回更新行；
- 精确边界重叠被保留为可审计的去重事件，而冲突重叠会 fail closed；
- 可复用下载器对任何直接调用者强制显式结束覆盖；
- 默认 live transport 对省略 `end` 的下载强制两周期加五分钟的新鲜度门禁，并在下载完成后采样参考时刻；
- 注入 getter 只有在显式提供 `as_of` 时才执行确定性新鲜度检查；
- canonical CLI 在 snapshot、回测和报告写入前再次复核结束覆盖。

完整软件门禁仍为：

```bash
ruff check .
ruff format --check .
pytest
```

## 更改周期时的配置责任

命令行 `--bar` 只覆盖数据周期。它不会自动缩放：

- `strategy.annualization`；
- momentum、reversal 和 volatility lookback；
- `selection_bars` 与 `test_bars`；
- 交易成本或任何稳健性阈值。

因此，从默认 `1Dutc` 改为小时或周线时，应创建并保存一份匹配该周期的新配置，重新解释所有“bar 数量”参数，并以 experiment manifest 记录有效配置。直接复用日线配置会改变实际时间跨度和年化指标，不能视为同一实验的简单数据覆盖。

默认、已验证的研究配置仍是：

```text
instrument: BTC-USDT / ETH-USDT spot
bar: 1Dutc
annualization: 365
```
