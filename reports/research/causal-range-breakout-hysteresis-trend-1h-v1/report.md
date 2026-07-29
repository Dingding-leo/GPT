# Causal range-breakout hysteresis trend — terminal research report

## Objective

Test whether an instrument-local price-range state machine can preserve persistent trend exposure with materially lower turnover than the daily 2,160H endpoint trend comparator. The frozen candidate enters only after a close exceeds the prior 2,160 completed-hour high and remains long until a close falls below the prior 720 completed-hour low.

```text
family_id              causal-range-breakout-hysteresis-trend-1h-v1
candidate_count        1
parameter_grid_count   0
canonical_fee          exactly 5 bps one-way
cadence                daily 00:00 UTC
execution              completed bar t -> open[t+1]
verdict                reject_exact_causal_range_breakout_hysteresis_trend_family
```

## Frozen temporal rule

For each instrument independently and using only completed observations strictly before the current level calculation:

```text
entry_level_t = max(high[t-2160:t])
exit_level_t  = min(low[t-720:t])

cash and close_t > entry_level_t  -> long
long and close_t < exit_level_t   -> cash
otherwise                         -> retain prior target
```

The current bar high/low is excluded, equality does not trigger, state carries across folds and sample boundaries, and every changed target executes at the next hourly open. No fitted threshold, trend gate, volatility filter, minimum hold, market-specific rule or parameter search was permitted.

## Immutable data and sample

| Market | Source artifact | CSV SHA-256 | Source observations | Loaded prefix |
|---|---:|---|---:|---:|
| BTC-USDT | 8704977298 | `92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9` | 43,941 | 43,441 |
| ETH-USDT | 8704978112 | `2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726` | 43,941 | 43,441 |

```text
source workflow       30401519824
warm-up               [0, 2,880)
training              [2,880, 17,520)   2021-11-21 through 2023-07-23 UTC
development OOS       [17,520, 43,440)  2023-07-24 through 2026-07-07 UTC
full scored           [2,880, 43,440)
OOS folds             12 x 2,160H
later suffix          semantically unread and unscored
```

Both prefixes passed source-hash, confirmed-bar, positivity, continuity, uniqueness, causal-level, next-open and exact fee-accounting checks.

## Training performance

| Market | Policy | Net return | Sharpe | Max DD | Turnover | Fees | Edge/turn | Exposure | Entries |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +24.29% | 0.652 | -21.73% | 1 | 0.05% | +2,681.64 bps | 28.19% | 1 |
| BTC-USDT | B0 hourly trend | -41.02% | -0.831 | -55.56% | 138 | 6.90% | -32.09 bps | 40.18% | 69 |
| BTC-USDT | B1 daily trend | -41.29% | -0.840 | -55.92% | 28 | 1.40% | -159.81 bps | 40.49% | 14 |
| ETH-USDT | Candidate | -27.81% | -0.179 | -54.18% | 2 | 0.10% | -701.93 bps | 53.61% | 1 |
| ETH-USDT | B0 hourly trend | -46.84% | -0.744 | -57.75% | 88 | 4.40% | -56.53 bps | 45.06% | 44 |
| ETH-USDT | B1 daily trend | -40.59% | -0.584 | -56.95% | 23 | 1.15% | -168.77 bps | 44.60% | 11 |

The candidate was extremely low turnover, but training already showed cross-market disagreement: BTC benefited from one long regime while ETH lost 27.81% despite only two position changes.

## Development-OOS performance

| Market | Policy | Net return | Sharpe | Max DD | Turnover | Fees | Edge/turn | Exposure | Entries |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +116.58% | 0.937 | -39.25% | 3 | 0.15% | +3,148.67 bps | 54.54% | 1 |
| BTC-USDT | B0 hourly trend | +111.64% | 0.917 | -22.68% | 203 | 10.15% | +45.31 bps | 57.25% | 101 |
| BTC-USDT | B1 daily trend | +119.68% | 0.954 | -26.55% | 45 | 2.25% | +212.75 bps | 57.32% | 22 |
| ETH-USDT | Candidate | **-41.43%** | **-0.012** | **-70.50%** | 4 | 0.20% | **-53.50 bps** | 78.80% | 2 |
| ETH-USDT | B0 hourly trend | +68.02% | 0.618 | -47.30% | 139 | 6.95% | +58.31 bps | 49.70% | 69 |
| ETH-USDT | B1 daily trend | +74.52% | 0.646 | -47.77% | 30 | 1.50% | +283.58 bps | 49.72% | 15 |

BTC nearly matched B1 return and Sharpe with only three position changes, but its drawdown was 12.70 percentage points worse and its paired incremental evidence was negative. ETH decisively rejected the hypothesis: the state machine remained exposed through prolonged reversals, lost 41.43%, and suffered a 70.50% drawdown.

## Full scored performance

| Market | Policy | Net return | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +169.19% | 0.845 | -39.25% | 4 | 0.20% | +3,031.91 bps |
| BTC-USDT | B1 | +28.97% | 0.332 | -55.92% | 73 | 3.65% | +69.85 bps |
| ETH-USDT | Candidate | **-57.72%** | **-0.064** | **-70.50%** | 6 | 0.30% | **-269.64 bps** |
| ETH-USDT | B1 | +3.68% | 0.233 | -56.95% | 53 | 2.65% | +87.28 bps |

The full-sample BTC point estimate was strong, but the identical ETH rule destroyed more than half of capital. Bilateral replication therefore failed.

## Breadth and uncertainty

| Market | Profitable folds | Profitable years | Positive-fold concentration | Residual Sharpe vs B0 / B1 | Mean delta L95 vs B1 | Sharpe delta L95 vs B1 |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 3/12 | 3/4 | 39.72% | +0.035 / -0.018 | -0.283873 | -0.808916 |
| ETH-USDT | 6/12 | 1/4 | 54.28% | -0.663 / -0.701 | -0.795515 | -1.579325 |

BTC failed the required 7/12 fold breadth despite positive annual segments. ETH failed fold breadth, year breadth and concentration. Neither market had a strictly positive paired-bootstrap lower bound; BTC's point delta versus B1 was slightly negative and ETH's was decisively negative.

## Failure mechanism

| Market | OOS overlapping episodes | Median duration | Profitable episodes | Worst episode | Candidate-only hours vs B1 | Candidate-only gross | B1-only hours | B1-only gross |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 2 | 7,068.5H | 100.0% | +3.41% | 3,504 | +21.37% | 4,224 | +24.74% |
| ETH-USDT | 3 | 5,304H | 33.3% | **-40.64%** | 8,904 | **-44.18%** | 1,368 | **+44.34%** |

The hysteresis did reduce turnover, but it did so by creating extremely persistent exposure rather than by improving state information. ETH's final OOS episode began at the 2024-11-09 01:00 UTC open, remained long through the 2026-07-08 sample boundary for 14,543 hours, and lost 40.64%. Its worst rolling candidate return was -35.28% over 168H and -44.59% over 720H.

ETH transition frequency did not collapse: training recorded one entry and one exit over 610 daily decisions; OOS recorded two entries and two exits over 1,080 decisions. The economic relationship failed even though signal frequency remained comparable. Range breaks held 8,904 hours when B1 was cash and those hours lost 44.18% arithmetically, while omitting 1,368 B1-long hours that gained 44.34%.

BTC's entry/exit state was also too coarse for the scorecard. It generated only three OOS changes and three profitable folds, missed more profitable B1-only gross contribution than it added in candidate-only exposure, and delivered a materially worse drawdown despite very high arithmetic edge per turnover.

## Diagnostic discrepancy repaired

The first episode diagnostic counted only long episodes whose entry occurred inside OOS. That omitted the long state inherited at the OOS boundary in both markets. Episode accounting was corrected to include every episode overlapping OOS and clip its duration and return to the scored interval.

The correction changed BTC episode count from 1 to 2 and ETH from 2 to 3. It did not change any feature, target, return, fee, comparator, acceptance gate or verdict, and it did not inspect the untouched suffix.

## Verdict

```text
reject_exact_causal_range_breakout_hysteresis_trend_family
```

The identical rule failed bilateral replication and multiple predeclared gates. No entry-window, exit-window, equality, trend-gate, volatility-gate, holding-period, cadence, execution, fee or market-specific rescue is authorised on this consumed development interval. There is no G1 nomination, prospective-paper promotion or live-trading authorisation.

## Remaining blocker and next experiment

No statistically eligible frozen causal 1H strategy exists.

Before any development-performance inspection, preregister one materially orthogonal own-history-only **low-frequency trend-coherence state**: project the trailing 2,160H demeaned log-price path onto one fixed linear trend basis and one fixed low-frequency residual basis; require positive causal slope plus a training-frozen high trend-energy share for entry; use one predeclared hysteretic transition to control turnover; one candidate, no parameter grid, daily next-open execution, exactly 5 bps one-way fees, immutable OKX 1H provenance, untouched-suffix protection and the same bilateral efficiency, drawdown, breadth, residual and paired-block uncertainty gates.
