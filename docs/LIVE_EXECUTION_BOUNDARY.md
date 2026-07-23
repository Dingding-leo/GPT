# 当前 `1Dutc` 信号与执行边界

本文件只描述仓库当前已经存在、可以从代码和配置复核的行为。它不是未来 live-trading 设计，也不提供账户、凭证或下单操作。

## 1. 当前可执行范围

当前可执行入口 `scripts/run_okx_research.py`：

- 使用 OKX 未认证公共历史 K 线接口；
- 默认研究 `BTC-USDT`、`ETH-USDT` 现货 `1Dutc`；
- 只保留 `confirm=1` 的完整 K 线；
- 生成真实数据 snapshot、rolling OOS 报告和 experiment manifest；
- 不读取账户，不创建 order intent，不模拟订单生命周期，也不发送订单。

仓库目前没有 paper broker、订单状态机、fill、reconciliation 或 live-order CLI。因此，在这些实现落地并通过门禁前，**没有可执行的 paper-run 或 live-run 命令**。

## 2. `1Dutc` 时间戳的含义

`config/okx_research.json` 当前声明：

```json
{
  "data": {
    "bar": "1Dutc"
  }
}
```

下载器把 OKX `ts` 转换为 UTC 时间索引，并要求 `1Dutc` 时间戳严格对齐 UTC 00:00。未完成的 `confirm=0` K 线会被排除。

该时间戳是交易所 K 线标签。当前 snapshot 没有独立保存以下生产时间：

- `market_data_received_at`；
- `decision_at`；
- `order_submitted_at`；
- `fill_at`；
- `fill_price_source`。

因此，看到一条 UTC 00:00 标签的完整日线，并不等于仓库已经证明可以在 UTC 00:00 按该行 close 成交。

## 3. 当前回测的精确记账顺序

`build_target_position()` 使用截至索引 `t` 的 close 数据计算 `target_position_t`。`run_backtest()` 随后执行：

```text
position_t        = target_position_{t-1}
asset_return_t    = close_t / close_{t-1} - 1
turnover_t        = abs(position_t - position_{t-1})
trading_cost_t    = turnover_t * transaction_cost_bps / 10000
strategy_return_t = position_t * asset_return_t - trading_cost_t
```

所以：

1. 在索引 `t` 计算出的 target 不会赚取同一行 `close_{t-1} -> close_t` 的收益；
2. 它最早影响索引 `t+1` 的 close-to-close 记账；
3. 该实现防止 target 使用同一行未来收益；
4. 它仍然没有定义真实订单何时提交、以哪个报价成交、是否部分成交或被拒绝。

结论：当前实现是**一根 bar 的记账延迟，不是 next-open 成交模型**。`target_position.shift(1)` 不能被描述为已经完成 next-open、UTC midnight、VWAP、TWAP 或盘口成交建模。

## 4. 当前成本边界

当前默认配置为：

```text
transaction_cost_bps = 5.0
cost_multipliers = [1.0, 1.5, 2.0, 3.0]
```

其含义是：

- 单边 `5 bps` 是每单位绝对仓位变化的交易所手续费研究基线；
- 每个 fold 的候选选择与 OOS 评估都在该 `5 bps` 基线下完整重新执行；
- `1.5 / 2.0 / 3.0` 倍只把已经选定的路径按单边 `7.5 / 10 / 15 bps` 重新计价，用于固定路径总成本敏感性；
- 这些压力路径不会在每个成本水平重新选择候选，也不能被描述为独立测量了某项执行摩擦。

当前模型没有独立字段或观测证据来拆分：

- bid-ask spread；
- slippage；
- market impact；
- latency cost；
- partial-fill 或 rejected-order cost。

所以允许描述“单边 5 bps 交易所手续费基线”，但不得把 `7.5 / 10 / 15 bps` 压力路径描述为已经分别验证了 spread、slippage、impact 或 latency，也不得把当前收盘价收益引擎描述为可执行成交模型。

固定已选路径重新计价与完整 walk-forward 候选选择是两个不同证据边界。只有 `5 bps` 基线路径执行完整候选重选；任何其他成本情景都必须明确标记为 fixed-path repricing。

## 5. 当前允许和禁止的表述

允许：

- “真实 OKX `1Dutc` 完整 K 线”；
- “one-bar-delayed close-to-close research accounting”；
- “单边 5 bps 交易所手续费基线”；
- “7.5 / 10 / 15 bps 固定已选路径总成本敏感性”；
- “研究系统尚未定义可执行成交价格”。

禁止：

- “next-open execution”；
- “日线收盘后按该 close 成交”；
- “已经 paper traded”；
- “已经验证真实 spread/slippage/impact/latency”；
- “7.5 / 10 / 15 bps 均完成重新选参”；
- “可以直接连接账户实盘”。

## 6. paper/live 文档的前置门禁

在仓库可以发布 paper-run 操作说明前，代码至少需要存在并通过测试的：

1. 明确的 `decision_at`、`order_submitted_at`、`fill_at` 和成交价格来源；
2. tick size、lot size、minimum notional、订单舍入和拒绝规则；
3. 不可变且幂等的 order intent；
4. paper broker 与订单/成交事件日志；
5. 持仓、现金、订单和 PnL 的持久状态；
6. restart replay 与外部状态 reconciliation；
7. stale-data、重复订单、异常换手、亏损和回撤 kill switches；
8. fee、spread、slippage、impact、latency 的独立归因；
9. 只读前向运行与回测/前向逐日对账。

在这些入口实际存在前，文档只能记录缺口和验收条件，不能编造尚不存在的操作步骤。

## 7. 可执行审计命令

检查当前 timeframe、基线费用和压力倍数：

```bash
python -c "import json,pathlib; c=json.loads(pathlib.Path('config/okx_research.json').read_text()); assert c['data']['bar']=='1Dutc'; assert c['strategy']['transaction_cost_bps']==5.0; assert c['robustness']['cost_multipliers']==[1.0,1.5,2.0,3.0]; print('bar=1Dutc fee_bps=5.0 total_cost_scenarios_bps=5,7.5,10,15')"
```

检查当前记账实现仍然使用一根 bar shift、close-to-close return 和线性换手成本：

```bash
python -c "from pathlib import Path; s=Path('src/gpt_quant/backtest.py').read_text(); required=('target_position.shift(1)','clean.pct_change()','turnover * config.transaction_cost_bps / 10_000.0','position * asset_return - trading_cost'); assert all(x in s for x in required); print('execution_accounting=verified')"
```

运行文档防漂移回归：

```bash
pytest -q tests/test_live_execution_boundary_documentation.py
```

这些命令只验证文档与当前代码/配置一致，不证明策略有 alpha，也不证明真实成交能力。
