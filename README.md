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

## OKX 滚动样本外实验

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
ruff check .
ruff format --check .
python scripts/run_okx_research.py --inst-id BTC-USDT --output-dir reports/okx/BTC-USDT
```

完整的真实数据复现流程、CLI 参数、输出文件、快照哈希核验和故障排查见 [`docs/REPRODUCTION.md`](docs/REPRODUCTION.md)。

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
6. 将交易成本提高到 2 倍和 4 倍；
7. 对回看期和信号权重做小幅扰动；
8. 报告区分“alpha 候选”和“低回撤风险控制候选”，不通过稳健性条件则标记为 `reject`。

默认成本假设为每单位换手 10 bps，是可配置的研究参数，不代表任何账户的实际 OKX 费率。

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

## 真实数据复现与回归

本项目禁止在研究、回测、示例、CI smoke test 和价格序列单元测试中使用合成、模拟或伪造行情。所有价格和成交量输入必须来自真实交易所历史数据，并保留来源、品种、周期、时间范围、原始响应和 SHA-256 证据。

`run_research.py` 当前仍包含无 `--csv` 时生成模拟价格的旧路径。该路径违反项目规则，不得执行，也不得作为测试或研究证据。仅允许将经过哈希核验的真实交易所快照显式传入：

```bash
python scripts/run_research.py \
  --csv reports/okx/BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.csv \
  --timestamp-col timestamp \
  --close-col close \
  --output-dir reports/holdout/BTC-USDT
```

不得使用无法追踪到交易所、请求参数和原始响应的任意 CSV。结构性拒绝测试可以删除或破坏真实快照副本中的字段来验证 fail-closed 行为，但被修改的数据不得用于计算或发布任何收益、Sharpe、回撤或其他表现指标。

## 每小时自动化

`.github/workflows/hourly-research.yml` 在每小时第 17 分钟运行。一个 workflow run 只有同时满足以下条件，才可被视为有效质量门禁：

- lint 与格式检查通过；
- 所有测试仅使用带来源和哈希的真实交易所快照；
- smoke test 使用真实交易所数据；
- BTC-USDT、ETH-USDT 公共日线下载与滚动样本外研究通过；
- 报告、原始响应、规范化快照和 provenance artifact 均已保存。

当前仓库中的 legacy synthetic smoke-test step 和任何生成价格的测试都是 P0 阻塞项；在它们被替换前，即使 workflow 显示绿色，也不能将相关 run 当作符合本项目数据政策的有效证据。

工作流对仓库只有读取权限，不会自动提交代码，不包含 API key，也不会向 OKX 发送订单。

## 研究纪律

1. 不用测试 fold 的结果选择该 fold 的参数。
2. 不展示未计成本的结果作为“净收益”。
3. 不使用合成、模拟、生成或无法溯源的行情数据。
4. 不在完成只读行情前向验证和风控验收前接入真实订单。
5. 不用单条收益曲线替代跨时期、跨市场、参数扰动和容量测试。
6. 任何数据下载都必须能由原始响应、请求参数和 SHA-256 哈希追踪。
7. 统计重采样只能重采样真实观测收益，且必须明确标注为重采样；不得生成虚构价格路径。

## 后续阶段

- 将 BTC-USDT、ETH-USDT 扩展为组合级和横截面测试；
- 增加 block bootstrap 置信区间、Deflated Sharpe 与 PBO；
- 使用盘口或成交数据建立滑点、冲击和容量模型；
- 保存不可变数据快照并建立结果变更审计；
- 通过只读行情的前向验证检验研究与实际执行的一致性。

> 本仓库仅用于研究和软件工程验证，不构成投资建议，也不保证收益或回撤。
