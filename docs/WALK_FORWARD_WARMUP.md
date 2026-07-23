# Walk-forward 选择窗口预热边界

本页说明 rolling out-of-sample 参数选择与稳健性扰动在一根 bar 延迟执行下必须满足的预热条件。它是研究有效性边界，不是为了提高策略指标而设置的调参规则。

## 必须满足的条件

设：

- `S = selection_bars`，即每个 fold 的参数选择窗口包含的价格行数；
- momentum 候选为 `m`，reversal 候选为 `r`；
- robustness 会为每个候选额外执行 `longer_lookbacks`：
  `max(2, round(1.2 * m))` 与 `max(1, round(1.2 * r))`；
- `L` 为所有实际执行配置需要的最大 lookback：所有较长 momentum 扰动、所有较长 reversal 扰动，以及 `strategy.volatility_lookback` 的最大值。

一个 lookback 为 `L` 的完整目标仓位最早只能在窗口内第 `L` 次收益之后形成。仓位随后由 `run_backtest()` 使用 `target_position.shift(1)` 延迟一根 bar 执行。因此，要让每个候选及其较长 lookback 扰动在选择窗口内至少产生一条由完整信号驱动的可执行收益，必须满足：

```text
selection_bars >= longest_required_lookback + 2
```

选择窗口内由最慢实际执行配置产生的可执行观测数为：

```text
selection_bars - longest_required_lookback - 1
```

只检查原始候选数组并不充分。一个原始 momentum 或 reversal 候选可能在选择窗口内已经预热完成，但它的 1.2 倍 `longer_lookbacks` 稳健性扰动仍可能没有任何延迟执行观测。该配置必须在任何 cache population、候选 backtest 或 fold 构造前失败，而不是生成全现金或缩短样本的稳健性指标。

## 当前 OKX 配置

`config/okx_research.json` 当前声明：

- `selection_bars = 730`；
- 最大 momentum 候选为 `180`，其较长扰动为 `round(180 * 1.2) = 216`；
- 最大 reversal 候选为 `10`，其较长扰动为 `round(10 * 1.2) = 12`；
- 固定 volatility lookback 为 `30`。

因此 `L = 216`，最慢实际执行配置在选择窗口内仍有 `730 - 216 - 1 = 513` 条延迟执行观测，满足研究协议。原始候选最大值 `180` 不是完整稳健性网格的最大 lookback。

在仓库根目录运行以下命令，可审计当前配置。该写法可在 Bash 和 PowerShell 中使用：

```bash
python -c "import json,pathlib; c=json.loads(pathlib.Path('config/okx_research.json').read_text()); s=c['search']; longer=lambda x,m:max(m,round(x*1.2)); L=max([*(longer(x,2) for x in s['momentum_lookbacks']),*(longer(x,1) for x in s['reversal_lookbacks']),c['strategy']['volatility_lookback']]); n=s['selection_bars']-L-1; assert n>=1, 'selection window has no delayed executable observation after candidate or longer-lookback perturbation'; print('longest_required_lookback=',L,'executable_selection_observations=',n)"
```

预期输出包含：

```text
longest_required_lookback= 216 executable_selection_observations= 513
```

## 当前实现与回归

`run_walk_forward_research()` 先构造并严格校验候选，再使用与 `_perturb()` 共用的 `_longer_lookbacks()` 公式计算每个候选可能执行的较长 momentum/reversal 扰动。它将这些值与 volatility lookback 一并取最大值，并执行以下边界：

```python
longest_lookback = max(
    max(candidate.volatility_lookback, *_longer_lookbacks(candidate))
    for candidate in candidates
)
if longest_lookback > selection_bars - 2:
    raise ValueError(
        "selection_bars must provide at least one one-bar-delayed "
        "selection-window observation after every candidate lookback "
        "and longer-lookback perturbation"
    )
```

因此：

- volatility 没有 1.2 倍较长扰动，其最后允许边界仍为 `selection_bars - 2`；
- momentum 与 reversal 必须按 `round(1.2 * lookback)` 后的实际扰动值判断，不能把原始 `lookback = selection_bars - 2` 当作可接受边界；
- 在测试使用的 `selection_bars = 300` 下，momentum/reversal 原始 lookback `248` 扩展为 `298` 并被接受，而 `250` 和 `251` 分别扩展为 `300` 和 `301`，会在任何 backtest 或 cache population 前被拒绝；
- validation 和执行使用同一个 `_longer_lookbacks()` helper，避免检查公式与实际扰动漂移。

仓库中的 immutable real OKX 回归分别锁定 API 边界和底层执行时序。运行：

```bash
python -m pytest -q \
  tests/test_walk_forward_lookback_boundary.py \
  tests/test_walk_forward_delayed_execution_boundary.py \
  tests/test_walk_forward_warmup_documentation.py
```

`test_walk_forward_lookback_boundary.py` 证明 volatility 的最后可执行边界以及 momentum/reversal 的最后可执行较长扰动边界能够进入 fold 并被计数；它也证明 under-warmed 原始候选或较长扰动在调用候选 backtest、填充 cache 或构造 fold 前失败。

`test_walk_forward_delayed_execution_boundary.py` 对 momentum、reversal 和 volatility 三类直接 lookback 验证：

- `selection_bars - 2` 的首个完整 target 出现在倒数第二行，并在最后一行形成恰好一条延迟执行 position；
- `selection_bars - 1` 的首个 target 只能出现在最后一行，因此选择窗口内所有 position 都为零。

该底层时序回归允许多空两种 position 符号，目的是避免真实数据上的完整信号被 long/cash 下限裁剪成现金；它验证执行对齐，不宣称现货 long/cash 候选在所有窗口都必然有非零 exposure。

## 证据边界

生产检查保证每个候选及其可能执行的较长 lookback 扰动在选择窗口中至少留有一条可执行观测的位置；底层回归进一步证明直接 lookback 边界在选定的 immutable real OKX 窗口中确实产生一条非零延迟 position。它不证明所有市场窗口都会产生非零 exposure，也不证明一条观测足以稳定估计候选或扰动指标、候选排名显著、策略优于基准，且不替代 rolling OOS、稳健性或 sealed-holdout 证据。
