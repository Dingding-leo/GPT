# GPT Quant Lab

一个从零构建、可复现、可审计的量化研究工程。当前版本的目标不是宣称“发现了西蒙斯策略”，而是先把最容易造假的环节做对：**时点一致、无未来函数、交易成本、风险约束、验证集选模和封存样本外测试**。

## 当前基线

单资产弱信号组合：

\[
s_t = w_T z_{\text{trend},t} + w_R z_{\text{reversal},t}
\]

波动率目标仓位：

\[
p_t^* = \operatorname{clip}\left(\tanh(s_t)\frac{\sigma^*}{\hat\sigma_t},-p_{\max},p_{\max}\right)
\]

回测中，收盘时刻 \(t\) 计算出的目标仓位只从下一根 bar 开始生效：

\[
r^{\text{strategy}}_t = p^*_{t-1}r_t-c\lvert p^*_{t-1}-p^*_{t-2}\rvert
\]

这条一根 bar 的执行延迟，是防止未来函数的最低要求之一。

当前包含：

- 趋势与短期反转弱信号组合；
- 滚动波动率目标和绝对仓位上限；
- 线性换手成本；
- CAGR、波动率、Sharpe、Sortino、最大回撤、Calmar、换手率等指标；
- 验证区间选参与最终封存 holdout 评估；
- 确定性多状态合成数据，用于 CI 和逻辑测试；
- 每小时 GitHub Actions：lint、测试、研究运行、报告 artifact。

## 本地运行

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest
python scripts/run_research.py --output-dir reports
```

报告会写入：

```text
reports/latest.json
reports/latest.md
```

## 使用自己的数据

CSV 至少需要时间和收盘价两列，默认列名为 `timestamp` 与 `close`：

```bash
python scripts/run_research.py \
  --csv data/prices.csv \
  --timestamp-col timestamp \
  --close-col close \
  --output-dir reports
```

研究参数位于 [`config/research.json`](config/research.json)。

## 每小时自动化

`.github/workflows/hourly-research.yml` 在每小时第 17 分钟运行，另支持手工触发。结果以 GitHub Actions artifact 保存 14 天；工作流只读仓库，不自动提交代码，也不连接券商或交易所。

## 研究纪律

1. 不用测试集反复调参；任何触碰 holdout 后的修改都应启用新的封存区间。
2. 不展示未计手续费、滑点和冲击成本的“净收益”。
3. 不把合成数据结果当成真实 alpha。
4. 不在未完成仿真、纸面交易和风控验收前接入真实订单。
5. 不用单条回测曲线替代跨时期、跨市场、参数扰动和容量测试。

## 下一阶段

- 接入可版本化的真实行情快照与数据质量检查；
- 增加多资产横截面研究、协方差估计和组合优化；
- 增加滚动 walk-forward、bootstrap 置信区间、Deflated Sharpe 与 PBO；
- 建立滑点、冲击、容量和成交约束模型；
- 通过纸面交易验证研究结果与实际执行的一致性。

> 本仓库仅用于研究和软件工程验证，不构成投资建议，也不会保证收益或回撤。
