# GPT Quant Lab

一个从零构建、可复现、可审计的量化研究工程。当前目标不是宣称“发现了西蒙斯策略”，而是先把最容易造假的环节做对：**时点一致、无未来函数、交易成本、风险约束、滚动样本外测试和数据来源追踪**。

## 当前研究对象

默认真实数据实验使用 OKX 公共 REST API 的 `BTC-USDT` 与 `ETH-USDT` 现货日线：

- 接口：`GET /api/v5/market/history-candles`；
- 周期：`1Dutc`，按 UTC 0 点划分日线；
- 只接受 `confirm=1` 的完整 K 线；
- 不需要 API key，不读取账户，不连接交易接口；
- 现货策略限制为 **长仓/现金**，不在现货回测中虚构卖空；
- 每次下载保存原始分页响应、规范化 OHLCV CSV、元数据及 SHA-256 哈希。

OKX 的历史 K 线是交易所特定数据；收盘价回测不能复现盘口深度、延迟或保证成交。API 域名具有地区差异，可通过 `OKX_BASE_URL` 或 `--base-url` 覆盖。

## 策略基线

单资产弱信号组合：

\[
s_t = w_T z_{\text{trend},t} + w_R z_{\text{reversal},t}
\]

波动率目标仓位：

\[
p_t^* = \operatorname{clip}\left(\tanh(s_t)\frac{\sigma^*}{\hat\sigma_t},p_{\min},p_{\max}\right)
\]

收盘时刻 \(t\) 计算出的目标仓位只从下一根 bar 开始生效：

\[
r^{\text{strategy}}_t = p^*_{t-1}r_t-c\lvert p^*_{t-1}-p^*_{t-2}\rvert
\]

这条一根 bar 的执行延迟，是防止未来函数的最低要求之一。

## 当前 `1Dutc` 信号、报价与绑定边界

当前代码可以用 OKX 公共、无认证的服务器时间验证最新完整日线是否已在交易所时间上收盘，并把响应、哈希和派生的 `signal_not_before_utc` 持久化为可重放证据。下游随后可以生成不可变目标意图、把 provider-neutral `ExecutionQuoteSnapshot` 写入私有不可变证据库并重放确定性根哈希，再用 `ExecutionQuoteBinding` 把准确的目标意图 ID、报价 ID、决策时刻和新鲜度策略绑定为一个确定性的 `binding_id`。

下面的离线命令使用仓库内带 SHA-256 来源的真实 OKX 小型快照，重放“完整 K 线 → 交易所时间证据 → 不可变目标意图 → 结构性报价持久化/重放 → 可重构报价绑定”：

```bash
python examples/signal_intent_timing.py \
  --output-dir reports/examples/signal-intent-timing
```

报价部分明确标记为结构性示例，不是 OKX 盘口抓取、订单或成交证据。`signal_not_before_utc`、bid/ask、midpoint、`snapshot_id` 和 `binding_id` 都不是订单或成交。当前仓库仍没有集成的 OKX 盘口生产器、持久化报价绑定、订单尺寸约束、纸面经纪商或成交日志。精确定义、时间顺序、重放边界和禁止的操作性声明见 [`docs/SIGNAL_INTENT_TIMING.md`](docs/SIGNAL_INTENT_TIMING.md)。

## OKX 滚动样本外实验

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest
python scripts/run_okx_research.py --inst-id BTC-USDT --output-dir reports/okx/BTC-USDT
```

可覆盖默认品种、周期、日期和 API 域名：

```bash
python scripts/run_okx_research.py \
  --inst-id ETH-USDT \
  --bar 1Dutc \
  --start 2018-01-01 \
  --base-url https://www.okx.com \
  --output-dir reports/okx/ETH-USDT
```

实验流程为：

1. 每个 fold 只用测试期之前的 730 根 K 线选择参数；
2. 在随后 90 根 K 线上做一次非重叠样本外评估；
3. fold 切换时按真实前一仓位重新计算换手与成本；
4. 同期比较买入持有、波动率目标长仓和简单趋势长仓/现金；
5. 所有基准从现金开始，并计入样本外起点的建仓成本；
6. 在单边 5 bps 交易所手续费下完成全部候选的逐 fold 选择，并将该已选路径分别按单边 7.5、10 和 15 bps 固定路径重新计价；
7. 对回看期和信号权重做小幅扰动；
8. 报告区分“alpha 候选”和“低回撤风险控制候选”，不通过稳健性条件则标记为 `reject`。

默认基线为每单位绝对仓位换手收取单边 5 bps **交易所手续费**。7.5、10 和 15 bps 是固定已选路径的总成本敏感性，不是已测量的点差、滑点、市场冲击或延迟。当前收盘价收益引擎仍不是可执行成交模型，也不代表任何账户的实际 OKX 费率。

报告会写入：

```text
reports/okx/BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.csv
reports/okx/BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.raw.json
reports/okx/BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.metadata.json
reports/okx/BTC-USDT/walk_forward.json
reports/okx/BTC-USDT/walk_forward.md
reports/okx/BTC-USDT/walk_forward_returns.csv
```

研究参数位于 [`config/okx_research.json`](config/okx_research.json)。

## 外部真实 CSV

验证/留出研究脚本只接受显式提供的外部真实市场 CSV，不再提供合成数据默认路径：

```bash
python scripts/run_research.py \
  --csv data/prices.csv \
  --timestamp-col timestamp \
  --close-col close \
  --output-dir reports/custom
```

CSV 必须包含可解析的时间戳和严格为正的收盘价。调用者负责保留数据提供方、下载参数和文件哈希等来源证据；没有来源证据的 CSV 结果不能视为可审计研究结果。

## 每小时自动化

`.github/workflows/hourly-research.yml` 在每小时第 17 分钟运行：

- lint 与格式检查；
- 使用公开 OKX 历史数据执行单元测试和未来数据不变性回归；
- 重新下载 BTC-USDT、ETH-USDT 公共日线并运行滚动样本外研究；
- 报告和原始数据快照作为 GitHub Actions artifact 保存 14 天。

工作流不会生成或上传合成研究结果。工作流对仓库只有读取权限，不会自动提交代码，不包含 API key，也不会向 OKX 发送订单。

## 研究纪律

1. 不用测试 fold 的结果选择该 fold 的参数。
2. 不展示未计成本的结果作为“净收益”。
3. 研究、CI 报告和可执行入口不使用合成数据。
4. 不在完成仿真、纸面交易和风控验收前接入真实订单。
5. 不用单条收益曲线替代跨时期、跨市场、参数扰动和容量测试。
6. 任何数据下载都必须能由原始响应和 SHA-256 哈希追踪。

## 后续阶段

- 将 BTC-USDT、ETH-USDT 扩展为组合级和横截面测试；
- 增加 block bootstrap 置信区间、Deflated Sharpe 与 PBO；
- 使用盘口或成交数据建立滑点、冲击和容量模型；
- 保存不可变数据快照并建立结果变更审计；
- 通过只读行情的前向仿真检验研究与实际执行的一致性。

> 本仓库仅用于研究和软件工程验证，不构成投资建议，也不保证收益或回撤。
