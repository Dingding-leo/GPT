# Walk-forward 选择窗口预热边界

本页说明 rolling out-of-sample 参数选择窗口在一根 bar 延迟执行下必须满足的预热条件。它是研究有效性边界，不是为了提高策略指标而设置的调参规则。

## 必须满足的条件

设：

- `S = selection_bars`，即每个 fold 的参数选择窗口包含的价格行数；
- `L` 为所有候选所需的最大 lookback：
  `max(momentum_lookbacks, reversal_lookbacks, strategy.volatility_lookback)`。

一个 lookback 为 `L` 的完整目标仓位最早只能在窗口内第 `L` 次收益之后形成。仓位随后由 `run_backtest()` 使用 `target_position.shift(1)` 延迟一根 bar 执行。因此，要让每个候选在选择窗口内至少产生一条由完整信号驱动的可执行收益，必须满足：

```text
selection_bars >= longest_candidate_lookback + 2
```

选择窗口内由最慢候选产生的可执行观测数为：

```text
selection_bars - longest_candidate_lookback - 1
```

仅仅让 `selection_bars` 比最大 lookback 大 `1` 并不充分：该候选可能在选择窗口内没有任何由完整信号驱动的已执行收益，却仍产生有限的全现金指标并参与排名。

## 当前 OKX 配置

`config/okx_research.json` 当前声明：

- `selection_bars = 730`；
- 最大 momentum lookback 为 `180`；
- 最大 reversal lookback 为 `10`；
- 固定 volatility lookback 为 `30`。

因此 `L = 180`，最慢候选在选择窗口内仍有 `730 - 180 - 1 = 549` 条延迟执行观测，满足研究协议。

在仓库根目录运行以下命令，可审计当前配置。该写法可在 Bash 和 PowerShell 中使用：

```bash
python -c "import json,pathlib; c=json.loads(pathlib.Path('config/okx_research.json').read_text()); s=c['search']; L=max([*s['momentum_lookbacks'],*s['reversal_lookbacks'],c['strategy']['volatility_lookback']]); n=s['selection_bars']-L-1; assert n>=1, 'selection window has no delayed executable observation'; print('longest_lookback=',L,'executable_selection_observations=',n)"
```

预期输出包含：

```text
longest_lookback= 180 executable_selection_observations= 549
```

## 当前实现与回归

`run_walk_forward_research()` 对 momentum、reversal 和 volatility 三类 lookback 取最大值，并执行以下等价边界：

```python
if longest_lookback > selection_bars - 2:
    raise ValueError(
        "selection_bars must provide at least one one-bar-delayed "
        "selection-window observation after every candidate lookback"
    )
```

因此：

- `lookback = selection_bars - 1` 会在任何候选 backtest 或 fold 构造之前被拒绝；
- `lookback = selection_bars - 2` 是最后一个允许的边界；
- 三类 lookback 都受同一检查保护。

仓库中的 immutable real OKX 回归分别锁定 API 边界和底层执行时序。运行：

```bash
python -m pytest -q \
  tests/test_walk_forward_lookback_boundary.py \
  tests/test_walk_forward_delayed_execution_boundary.py \
  tests/test_walk_forward_warmup_documentation.py
```

`test_walk_forward_lookback_boundary.py` 证明最后允许的候选能够进入 fold 并被计数，同时证明下一条 under-warmed 边界在调用候选 backtest 前失败。

`test_walk_forward_delayed_execution_boundary.py` 对 momentum、reversal 和 volatility 三类 lookback 直接验证：

- `selection_bars - 2` 的首个完整 target 出现在倒数第二行，并在最后一行形成恰好一条延迟执行 position；
- `selection_bars - 1` 的首个 target 只能出现在最后一行，因此选择窗口内所有 position 都为零。

该底层时序回归允许多空两种 position 符号，目的是避免真实数据上的完整信号被 long/cash 下限裁剪成现金；它验证执行对齐，不宣称现货 long/cash 候选在所有窗口都必然有非零 exposure。

## 证据边界

生产检查保证每个候选在选择窗口中至少留有一条可执行观测的位置；底层回归进一步证明该边界在选定的 immutable real OKX 窗口中确实产生一条非零延迟 position。它不证明所有市场窗口都会产生非零 exposure，也不证明窗口足够长、候选排名稳定、策略显著优于基准，且不替代 rolling OOS、稳健性或 sealed-holdout 证据。
