# Walk-forward 报告审计

`walk_forward.json` 同时保存每个 OOS fold 的实际选中参数、聚合后的参数稳定性摘要和正式绩效指标。审计时不要只读取格式化字符串，也不要把已经破产的收益路径继续复利；应先复核结构化参数记录，再确认被计量的收益路径始终可偿付。

## 参数稳定性规范字段

机器可读的规范路径是：

```text
parameter_stability.selection_frequency_records
```

每条记录包含：

- `momentum_lookback`：严格整数；
- `reversal_lookback`：严格整数；
- `trend_weight`：有限实数，保留实际选中的浮点值；
- `selections`：该精确参数三元组被选中的 fold 数。

`parameter_stability.selection_frequency` 仍为兼容旧消费者保留，但它的 key 是展示字符串。自动审计、结果变更比较和参数切换分析应优先使用 `selection_frequency_records`，不能先把 `trend_weight` 四舍五入后再合并。`0.7` 与 `0.70000000001` 是两个不同的候选身份。

## 参数稳定性复核命令

先完成 BTC-USDT rolling OOS 研究，再从仓库根目录运行以下跨平台命令。它会根据 `folds[*].selected_parameters` 独立重建频率，并要求与结构化记录完全一致。

<!-- walk-forward-stability-audit:start -->
```bash
python -c "import collections,json,pathlib; p=json.loads(pathlib.Path('reports/okx/BTC-USDT/walk_forward.json').read_text()); expected=collections.Counter((f['selected_parameters']['momentum_lookback'],f['selected_parameters']['reversal_lookback'],f['selected_parameters']['trend_weight']) for f in p['folds']); observed=collections.Counter({(r['momentum_lookback'],r['reversal_lookback'],r['trend_weight']):r['selections'] for r in p['parameter_stability']['selection_frequency_records']}); assert observed==expected; print('parameter_stability=verified')"
```
<!-- walk-forward-stability-audit:end -->

成功输出：

```text
parameter_stability=verified
```

断言失败表示 fold 明细和稳定性摘要不一致。不要通过删除 fold、改写参数、四舍五入权重或手动修补计数来绕过失败；应回到生成该报告的 exact commit、配置、数据快照和运行日志定位原因。

## 参数稳定性写入边界

`WalkForwardResult.to_dict()` 会：

1. 深拷贝公开 payload，避免调用者修改返回值后污染结果对象；
2. 从 fold 明细重新计算 legacy 稳定性字段；
3. 拒绝 `selection_frequency`、`parameter_switches`、`parameter_switch_rate` 或 `unique_parameter_sets` 与 fold 明细不一致的结果；
4. 生成 `selection_frequency_records`。

`write_walk_forward_report()` 在创建输出目录和写入任何报告文件之前调用该验证。因此，已知不一致的稳定性 payload 不应留下部分 JSON、Markdown 或 returns artifact。

## 收益路径偿付边界

`performance_metrics()` 会在复利、CAGR、Sharpe、Sortino、最大回撤、Calmar、候选评分和报告生成之前检查当前被评估 frame 的 `strategy_return`。只要任意一行满足：

```text
strategy_return <= -1.0
```

就会 fail closed，并报告第一处位置：

```text
strategy return must remain greater than -100%; insolvency occurs at <timestamp-or-index>
```

`-1.0` 表示资本归零；小于 `-1.0` 表示负资本。继续对这种路径做复利会产生没有经济意义的后续 NAV 和指标。不要删除、截断、夹紧或改写失败行来获得可报告结果；应检查交易成本、换手、仓位归一化和窗口重定价，修复导致破产的真实原因后重新运行。

该检查只读取传入的当前 frame。未来才发生的破产不会污染在它之前单独提交给 `performance_metrics()` 的因果前缀；完整包含破产行的 frame 必须失败。固定 validation/holdout 研究会在候选评分之前调用指标函数，`scripts/run_research.py` 也只会在 `run_holdout_research()` 成功返回后写 `latest.json` 与 `latest.md`。OKX rolling 入口可能已经保存输入 snapshot，但破产的评估窗口不得生成或被当作有效绩效证据。

使用仓库内不可变真实 OKX BTC-USDT fixture 复核此边界：

```bash
pytest tests/test_insolvency_validation.py
```

该回归覆盖真实回测因极端成本破产、未来破产前缀保持可评估，以及在真实回测 frame 的副本中结构性注入 `-100%` 返回值后必须拒绝。结构性修改只用于 fail-closed 验证，不用于计算或报告绩效。

## 证据边界

参数稳定性校验只证明报告内部的参数身份与计数一致；偿付校验只证明被计量路径没有单期归零或负资本。两者都不证明参数选择具有统计显著性，也不把 BTC-USDT 或 ETH-USDT development evidence 变成 untouched holdout evidence。
