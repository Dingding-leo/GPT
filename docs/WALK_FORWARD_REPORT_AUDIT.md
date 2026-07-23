# Walk-forward 参数稳定性审计

`walk_forward.json` 同时保存每个 OOS fold 的实际选中参数，以及聚合后的参数稳定性摘要。审计时不要只读取格式化字符串；应使用结构化记录，并把它们重新与 fold 逐项核对。

## 规范字段

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

## 复核命令

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

## 写入边界

`WalkForwardResult.to_dict()` 会：

1. 深拷贝公开 payload，避免调用者修改返回值后污染结果对象；
2. 从 fold 明细重新计算 legacy 稳定性字段；
3. 拒绝 `selection_frequency`、`parameter_switches`、`parameter_switch_rate` 或 `unique_parameter_sets` 与 fold 明细不一致的结果；
4. 生成 `selection_frequency_records`。

`write_walk_forward_report()` 在创建输出目录和写入任何报告文件之前调用该验证。因此，已知不一致的稳定性 payload 不应留下部分 JSON、Markdown 或 returns artifact。

该校验只证明报告内部的参数身份与计数一致。它不证明参数选择具有统计显著性，也不把 BTC-USDT 或 ETH-USDT development evidence 变成 untouched holdout evidence。
