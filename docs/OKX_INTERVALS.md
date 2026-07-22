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

## 下载后的连续性检查

下载器会先解析原始 OKX 行、去除重复时间戳、排除 `confirm != 1` 的未完成 candle，并应用 `start`/`end` 范围。随后：

1. 每个相邻时间差必须是声明周期的整数倍；否则报 `off-cadence intervals`；
2. 整数倍大于 1 表示缺失一个或多个预期周期，下载器会报 `missing ... expected intervals`；
3. 指定 `--start` 时，只有 `max_pages` 用尽且最早返回 bar 仍晚于请求起点才会失败。若 OKX 先返回短页，或在已有数据后返回空页，下载器会保留可用历史，并分别记录 `pagination_termination=short_page` 或 `empty_page`；此时 `requested_start_reached` 可以为 `false`，例如品种上市晚于请求日期。

审计覆盖范围时必须同时检查 `pagination_termination` 与 `requested_start_reached`。成功完成下载并不等于请求起点一定已到达；若研究要求固定起始日期，应在下游门禁中显式拒绝 `requested_start_reached=false`，或先核实品种上市历史并调整研究起点。

这些检查发生在 walk-forward、指标计算和 artifact 写入之前。

## 可执行自检

从已安装开发依赖的干净检出运行：

```bash
pytest tests/test_okx_cadence.py
```

该测试使用仓库内真实 OKX fixture 的结构性副本验证：

- 已支持固定宽度标识的秒数映射；
- 日历月周期在网络请求前被拒绝；
- 均匀稀疏的 `1Dutc` 历史不能把两天间隔重新解释成完整日线。

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
