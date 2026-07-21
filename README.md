# GPT Quant Lab

一个从零构建、可复现、可审计的量化研究工程。当前目标不是宣称“发现了西蒙斯策略”，而是先把最容易造假的环节做对：**时点一致、无未来函数、交易成本、风险约束、滚动样本外测试和数据来源追踪**。

## 当前研究对象

默认真实数据实验使用 OKX 公共 REST API 的 `BTC-USDT` 现货日线：

- 接口：`GET /api/v5/market/history-candles`；
- 周期：`1Dutc`，按 UTC 0 点划分日线；
- 只接受 `confirm=1` 的完整 K 线；
- 不需要 API key，不读取账户，不连接交易接口；
- BTC-USDT 现货策略限制为 **长仓/现金**，不在现货回测中虚构卖空；
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
pytest
python scripts/run_okx_research.py --output-dir reports/okx
```

可覆盖默认品种、周期、日期和 API 域名：

```bash
python scripts/run_okx_research.py \
  --inst-id ETH-USDT \
  --bar 1Dutc \
  --start 2018-01-01 \
  --base-url https://www.okx.com \
  --output-dir reports/okx-eth
```

实验流程为：

1. 每个 fold 只用测试期之前的 730 根 K 线选择参数；
2. 在随后 90 根 K 线上做一次非重叠样本外评估；
3. fold 切换时按真实前一仓位重新计算换手与成本；
4. 同期比较买入持有、波动率目标长仓和简单趋势长仓/现金；
5. 将交易成本提高到 2 倍和 4 倍；
6. 对回看期和信号权重做小幅扰动；
7. 不通过稳健性条件时，报告直接标记为 `reject`。

默认成本假设为每单位换手 10 bps，是可配置的研究参数，不代表任何账户的实际 OKX 费率。

报告会写入：

```text
reports/okx/snapshot/okx-BTC-USDT-1Dutc.csv
reports/okx/snapshot/okx-BTC-USDT-1Dutc.raw.json
reports/okx/snapshot/okx-BTC-USDT-1Dutc.metadata.json
reports/okx/walk_forward.json
reports/okx/walk_forward.md
reports/okx/walk_forward_returns.csv
```

研究参数位于 [`config/okx_research.json`](config/okx_research.json)。

## 合成数据回归测试

合成多状态数据仍然保留，用于 CI、未来函数测试和回测逻辑回归，不作为真实 alpha 证据：

```bash
python scripts/run_research.py --output-dir reports/synthetic
```

也可以使用自己的 `timestamp`、`close` CSV：

```bash
python scripts/run_research.py \
  --csv data/prices.csv \
  --timestamp-col timestamp \
  --close-col close \
  --output-dir reports/custom
```

## 每小时自动化

`.github/workflows/hourly-research.yml` 在每小时第 17 分钟运行：

- lint 与格式检查；
- 单元测试和未来函数回归测试；
- 合成数据管线检查；
- OKX 公共日线下载与滚动样本外研究；
- 报告和原始数据快照作为 GitHub Actions artifact 保存 14 天。

工作流对仓库只有读取权限，不会自动提交代码，不包含 API key，也不会向 OKX 发送订单。

## 研究纪律

1. 不用测试 fold 的结果选择该 fold 的参数。
2. 不展示未计成本的结果作为“净收益”。
3. 不把合成数据或单次漂亮回测当成真实 alpha。
4. 不在完成仿真、纸面交易和风控验收前接入真实订单。
5. 不用单条收益曲线替代跨时期、跨市场、参数扰动和容量测试。
6. 任何数据下载都必须能由原始响应和 SHA-256 哈希追踪。

## 后续阶段

- 增加 ETH-USDT 等多品种的横截面及组合级测试；
- 增加 block bootstrap 置信区间、Deflated Sharpe 与 PBO；
- 使用盘口或成交数据建立滑点、冲击和容量模型；
- 保存不可变数据快照并建立结果变更审计；
- 通过只读行情的前向仿真检验研究与实际执行的一致性。

> 本仓库仅用于研究和软件工程验证，不构成投资建议，也不保证收益或回撤。
