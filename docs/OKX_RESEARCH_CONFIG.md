# OKX 滚动研究配置边界

本页说明 `config/okx_research.json` 中直接控制单资产策略、rolling out-of-sample 参数搜索和成本压力测试的字段，并说明 `config/okx_holdout.json` 复用的候选与 ranking 控制。实际执行入口是 `scripts/run_okx_research.py`：`strategy` 先由 `gpt_quant.StrategyConfig` 校验，rolling search 与 robustness 控制随后由 `gpt_quant.walk_forward.run_walk_forward_research()` 校验。

配置值的 **JSON 类型是研究协议的一部分**。入口不会把字符串、布尔值或小数静默转换成另一种有效参数。类型或范围不正确时，研究会在价格处理、候选回测和报告生成前 fail closed。

## `strategy` 参数

| 字段 | 必须使用的 JSON 类型 | 约束 |
|---|---|---|
| `momentum_lookback` | integer | 非布尔整数，至少为 `2`。 |
| `reversal_lookback` | integer | 非布尔整数，至少为 `1`。 |
| `volatility_lookback` | integer | 非布尔整数，至少为 `2`。 |
| `annualization` | integer | 非布尔整数，至少为 `2`。`1Dutc` 默认使用 `365`。 |
| `target_volatility` | number | 非布尔、有限实数，位于 `(0, 2]`。 |
| `max_abs_position` | number | 非布尔、有限实数，位于 `(0, 10]`。 |
| `min_position` | number 或 `null` | 数值必须位于 `[-max_abs_position, max_abs_position]`。`null` 会解析为 `-max_abs_position`；OKX 现货长仓/现金基线必须显式使用 `0.0`。 |
| `trend_weight` | number | 非布尔、有限且非负。 |
| `reversal_weight` | number | 非布尔、有限且非负；两个 signal weight 不能同时为零。 |
| `transaction_cost_bps` | number | 非布尔、有限且非负，按每单位换手的基点数解释。 |

`trend_weight` 和 `reversal_weight` 在生成信号时会按二者之和归一化。改变二者的共同缩放比例不会改变归一化权重，但仍会改变声明的配置和配置哈希；不要把等比例重复配置当作新候选。

以下声明会被拒绝，而不是被转换：

```json
{
  "strategy": {
    "momentum_lookback": 90.0,
    "volatility_lookback": "30",
    "target_volatility": "0.5",
    "max_abs_position": true,
    "min_position": "0.0",
    "transaction_cost_bps": false,
    "annualization": 365.0
  }
}
```

JSON 数字 `90.0` 与整数 `90` 在 timing controls 中不是同一种声明。字符串形式的数字和布尔值也不会被 Python 的 `int(...)` 或 `float(...)` 静默接受。

当前 OKX 现货基线显式设置 `min_position: 0.0`，因此仓位只能处于长仓/现金区间。删除该字段或改为 `null` 会恢复 `StrategyConfig` 的对称下限 `-max_abs_position`，这不符合当前现货研究假设，也不能与既有报告视为同一实验。

## `search` 参数

| 字段 | 必须使用的 JSON 类型 | 约束 |
|---|---|---|
| `momentum_lookbacks` | array | 每项必须是非布尔整数且至少为 `2`；数组不能为空。 |
| `reversal_lookbacks` | array | 每项必须是非布尔整数且至少为 `1`；数组不能为空。 |
| `trend_weights` | array | 每项必须是非布尔、有限的实数，并位于 `[0, 1]`；数组不能为空。 |
| `selection_bars` | integer | 必须至少为 `100`，并严格大于全部候选 lookback。 |
| `test_bars` | integer | 必须至少为 `20`。 |

以下写法不会被自动修正：

```json
{
  "search": {
    "selection_bars": "730",
    "test_bars": 90.0,
    "momentum_lookbacks": [30, true],
    "trend_weights": [0.55, "0.70"]
  }
}
```

其中字符串、布尔值和小数形式的窗口长度都会被拒绝。JSON 数字 `90.0` 与整数 `90` 在研究协议中不是同一种声明。

候选组合由三个数组的笛卡尔积构成。完全相同的规范化组合会去重，但不得依赖去重来掩盖重复实验；experiment manifest 和报告中的 candidate count 仍应由审计者核对。

## 固定 holdout 的切分、候选与 ranking 控制

`config/okx_holdout.json` 复用上面的完整 `strategy` 和三个候选数组。候选数组进入 `run_holdout_research()` 时使用相同的严格类型与范围校验；字符串、布尔值、小数形式的 lookback、非有限权重和空数组不会被转换成有效候选。

固定 validation / sealed-holdout 入口还声明：

| 字段 | 必须使用的 JSON 类型 | 约束 |
|---|---|---|
| `validation_fraction` | number | 非布尔、有限实数，位于 `[0.05, 0.40]`。 |
| `holdout_fraction` | number | 非布尔、有限实数，位于 `[0.05, 0.40]`。 |
| `top_candidates` | integer | 非布尔正整数；`0`、负数、字符串、布尔值和小数都会被拒绝。 |

`validation_fraction` 与 `holdout_fraction` 的和必须严格小于 `0.80`，以保留足够的早期历史用于候选训练。入口不再对 `"0.2"`、`true` 或其他错误类型调用 `float(...)`；这些值会在价格校验、候选回测和报告目录创建前失败。程序化调用中的 `NaN` 或无穷值也会被拒绝。当前配置使用 `0.20` validation 和 `0.20` sealed holdout。

切分按清洗后观测数计算：最后 `holdout_fraction` 部分只用于一次 sealed-holdout 评估，紧邻其前的 `validation_fraction` 部分用于候选排名，更早的部分用于候选训练。改变任一比例都会改变三个时间边界和有效实验身份。它们不替代 rolling 配置中的 `selection_bars` 与 `test_bars`；两种协议的指标不能直接互当复算结果，完整复现流程见 [`REPRODUCTION.md`](REPRODUCTION.md)。

`top_candidates` 只限制报告中 `candidate_ranking` 保存多少个最高排名候选，不会减少实际搜索的组合数，也不会改变 `candidates_tested`。当前三个 `3` 项数组形成 `3 × 3 × 3 = 27` 个候选；配置保存前 `10` 名，但报告仍必须记录已测试 `27` 个候选。不得把较小的 ranking 列表误报为较小的 multiple-testing 暴露。

## `robustness.cost_multipliers`

`cost_multipliers` 必须是 JSON array。每项必须是非布尔、有限且严格为正的实数。

有效示例：

```json
{
  "robustness": {
    "cost_multipliers": [1.0, 2.0, 4.0]
  }
}
```

以下值会被拒绝：

- 字符串，例如 `"2"`；
- 布尔值，例如 `true`；
- `0` 或负数；
- 非有限数值。

运行时会确保 `1.0` 和 `2.0` 两个压力倍数存在，然后对有效倍数去重并排序。报告与 experiment manifest 保存的是规范化后的有效倍数，而不是未经校验的原始声明。

## 当前默认值

当前 `config/okx_research.json` 的关键声明为：

```json
{
  "strategy": {
    "momentum_lookback": 90,
    "reversal_lookback": 5,
    "volatility_lookback": 30,
    "target_volatility": 0.5,
    "max_abs_position": 1.0,
    "min_position": 0.0,
    "trend_weight": 0.7,
    "reversal_weight": 0.3,
    "transaction_cost_bps": 10.0,
    "annualization": 365
  },
  "search": {
    "momentum_lookbacks": [30, 90, 180],
    "reversal_lookbacks": [2, 5, 10],
    "trend_weights": [0.55, 0.7, 0.85],
    "selection_bars": 730,
    "test_bars": 90
  },
  "robustness": {
    "cost_multipliers": [1.0, 2.0, 4.0]
  }
}
```

当前 `config/okx_holdout.json` 的切分与 ranking 声明为：

```json
{
  "search": {
    "validation_fraction": 0.2,
    "holdout_fraction": 0.2,
    "top_candidates": 10
  }
}
```

更改这些字段会改变策略、候选数量、选择窗口、OOS fold 数量、固定切分边界或成本压力证据，应生成新的有效配置哈希和 experiment identity，不能与旧报告视为同一次实验。

## 验证

检查 JSON 是否可解析：

```bash
python -m json.tool config/okx_research.json
python -m json.tool config/okx_holdout.json
```

执行 strategy、rolling controls、holdout controls 和 fail-closed 回归：

```bash
pytest \
  tests/test_strategy_config_type_validation.py \
  tests/test_walk_forward_control_validation.py \
  tests/test_holdout_candidate_validation.py \
  tests/test_okx_research_config_documentation.py
```

完整研究仍应通过仓库统一门禁：

```bash
ruff check .
ruff format --check .
pytest
```

这些检查不证明策略有效，只证明当前配置能够按声明执行，并且错误类型不会被静默转换成不同的研究参数。
