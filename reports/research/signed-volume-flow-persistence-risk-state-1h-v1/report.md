# Signed-volume-flow persistence risk state — terminal report

## Objective and frozen architecture

Test whether an instrument-local, scale-free directional participation state can improve the daily 2,160H slow-trend policy without delaying entry or imposing irreversible lockout. Candidate count is **1**, parameter-grid count is **0**, decisions use completed daily 00:00 UTC bars, execution is at the next hourly open, and every absolute exposure change pays exactly **5 bps one way**.

```text
hourly_sign_i = sign(log(close_i / close_(i-1)))
flow168_t     = sum(volume_quote_i × hourly_sign_i) / sum(volume_quote_i)
                over completed hours [t-167, t]
flow168_prev  = the same measure over [t-335, t-168]
risk_t        = flow168_t < 0 and flow168_t < flow168_prev
recovery_t    = flow168_t > 0 and flow168_t > flow168_prev
```

At a new positive 2,160H trend onset, exposure is `1.0`. While the trend remains positive, a risk trigger sets exposure to `0.5`, a recovery trigger sets it to `1.0`, and an ambiguous state retains the prior exposure. A non-positive base trend forces cash.

## Immutable data and sample

| Item | Frozen value |
|---|---|
| Provider | Public confirmed OKX SPOT |
| Markets | BTC-USDT and ETH-USDT independently |
| Source artifacts | BTC `8704977298`; ETH `8704978112` |
| Source SHA-256 | BTC `92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9`; ETH `2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726` |
| Parsed immutable prefix | 43,441 confirmed contiguous 1H bars |
| Training | `[2,880,17,520)` |
| Development OOS | `[17,520,43,440)` |
| Full scored | `[2,880,43,440)` |
| Breadth | 12 contiguous 2,160H folds plus calendar years |
| Uncertainty | 5,000 paired non-circular 168H blocks; seed `20260730` |
| Later suffix | Unread and unscored |

## Performance

### Training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | -35.88% | -0.924 | -50.11% | 42.0 | 2.10% | -93.03 bps |
| BTC-USDT | B1 daily | -41.29% | -0.840 | -55.92% | 28.0 | 1.40% | -159.81 bps |
| ETH-USDT | Candidate | -9.52% | -0.060 | -42.34% | 34.5 | 1.73% | -8.49 bps |
| ETH-USDT | B1 daily | -40.59% | -0.584 | -56.95% | 23.0 | 1.15% | -168.77 bps |

The candidate reduced training loss and drawdown in both markets, especially ETH. BTC Sharpe deteriorated and turnover increased materially; both candidates remained negative.

### Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +79.79% | 0.861 | **-21.79%** | 80.5 | 4.03% | 86.65 bps |
| BTC-USDT | B0 hourly | +111.64% | 0.917 | -22.68% | 203.0 | 10.15% | 45.31 bps |
| BTC-USDT | B1 daily | **+119.68%** | **0.954** | -26.55% | **45.0** | 2.25% | **212.75 bps** |
| ETH-USDT | Candidate | **+94.53%** | **0.841** | **-36.02%** | 60.0 | 3.00% | 138.32 bps |
| ETH-USDT | B0 hourly | +68.02% | 0.618 | -47.30% | 139.0 | 6.95% | 58.31 bps |
| ETH-USDT | B1 daily | +74.52% | 0.646 | -47.77% | **30.0** | 1.50% | **283.58 bps** |

BTC improved drawdown but sacrificed **39.89 percentage points** of compounded return versus B1, reduced Sharpe, increased turnover by 78.9%, and lost most of B1's edge per turnover.

ETH produced a strong point estimate: **+20.01 percentage points** more compounded return, `+0.195` Sharpe, and an **11.74-point** drawdown improvement versus B1. The gain required twice B1 turnover and delivered less than half B1's edge per turnover.

### Full scored sample

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +15.29% | 0.249 | -50.11% | 122.5 | 6.13% | 25.05 bps |
| BTC-USDT | B1 daily | **+28.97%** | **0.332** | -55.92% | **73.0** | 3.65% | **69.85 bps** |
| ETH-USDT | Candidate | **+76.01%** | **0.542** | **-42.34%** | 94.5 | 4.73% | 84.72 bps |
| ETH-USDT | B1 daily | +3.68% | 0.233 | -56.95% | **53.0** | 2.65% | **87.28 bps** |

## Breadth and uncertainty

| Market | Profitable folds | Profitable years | Folds / years improved vs B1 | Concentration | Residual Sharpe | Annualised mean delta 95% | Sharpe delta 95% |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 6/12 | 3/4 | 5/12; 1/4 | 33.48% | -0.759 | [-21.75%, +2.99%] | [-0.419, +0.215] |
| ETH-USDT | 6/12 | 3/4 | 6/12; 2/4 | 25.87% | -0.041 | [-18.17%, +16.58%] | [-0.196, +0.569] |

Neither market reached the required 7/12 profitable folds. Both residual Sharpes were negative and every dependence-aware lower confidence bound was below zero.

## Failure mechanism

### Feature activation was stable

| Market | Effective transition frequency, training | Effective transition frequency, OOS |
|---|---:|---:|
| BTC-USDT | 13.73% | 13.23% |
| ETH-USDT | 12.64% | 12.84% |

The feature did not disappear. Its conditional economics differed across markets.

### BTC: the risk state removed stronger continuation

BTC had 43 effective risk transitions and 36 effective recovery transitions OOS. Effective risk transitions were followed by mean returns of **+0.33% over 24H** and **+2.87% over 168H**, with 67.44% positive 168H outcomes.

The half-risk state occupied 6,673 hours, or 44.91% of B1 long exposure. Those hours carried **+48.42%** arithmetic market return and a conditional annualised Sharpe of **1.394**, above the full-exposure state's `1.202`. The policy halved exposure during unusually productive BTC continuation.

```text
full-exposure-equivalent hours removed   3,336.5
market return removed                    +24.21%
incremental fees                         +1.78%
arithmetic net delta                     -25.98%
```

BTC's 44 half-state episodes were not event-concentrated: 28 were positive and 16 negative, with the largest episode representing 9.35% of half-state hours. The failure was systematic sign error, not one outlier.

### ETH: meaningful state separation, but no robust net superiority

ETH had 37 effective risk transitions and 30 effective recovery transitions OOS. Effective risk transitions were followed by a mean **-0.66%** return over 168H. The half-risk state occupied 6,528 hours, or 50.65% of B1 long exposure, but carried only **+1.17%** total market return and a conditional annualised Sharpe of `0.023`. Full-exposure hours carried **+85.40%** and a conditional Sharpe of `2.032`.

```text
full-exposure-equivalent hours removed   3,264.0
market return removed                    +0.59%
incremental fees                         +1.50%
arithmetic net delta                     -2.09%
```

The compounded improvement came from variance and sequencing, not a positive arithmetic mean delta. It appeared in only 6/12 folds and 2/4 calendar years versus B1, with negative residual Sharpe and confidence intervals crossing zero.

### Repaired diagnostic discrepancy

The first diagnostic pooled raw trigger observations with economically effective state changes. Terminal evidence separates persistent same-state triggers from transitions:

```text
BTC raw risk/recovery triggers       201 / 232
BTC effective risk/recovery changes   43 / 36
BTC repeated same-state triggers     158 / 196

ETH raw risk/recovery triggers       214 / 186
ETH effective risk/recovery changes   37 / 30
ETH repeated same-state triggers     177 / 156
```

Turnover is reconstructed exactly:

```text
BTC onset 22.0 + base exit 19.0 + risk 21.5 + recovery 18.0 = 80.5
ETH onset 15.0 + base exit 11.5 + risk 18.5 + recovery 15.0 = 60.0
```

No signal, position, fee, metric, bootstrap result, gate or verdict changed. Two complete executions produced byte-identical `result.json` files.

## Verdict

```text
reject_exact_signed_volume_flow_persistence_risk_state_family
```

BTC failed benchmark return, Sharpe, turnover, edge per turnover, fold breadth, residual Sharpe and both uncertainty gates. ETH failed turnover, edge per turnover, fold breadth, residual Sharpe and both uncertainty gates.

No same-interval flow window, weighting, sign convention, threshold, exposure fraction, hysteresis, cadence, fee or market-specific rescue is authorised. There is no G1 nomination, prospective-paper promotion or live-trading authorisation.

## Remaining blocker and next experiment

**Remaining blocker:** directional participation is not bilaterally transportable. It identifies low-quality ETH exposure but labels strong BTC continuation as risk, while recurring state changes consume too much edge.

**Next experiment:** one own-history-only four-phase daily trend ensemble. Evaluate the unchanged 2,160H endpoint trend on fixed 00:00, 06:00, 12:00 and 18:00 UTC decision phases and set unlevered exposure to the fraction of positive phase states. This directly tests temporal decision-phase robustness with one candidate, no fitted threshold, no grid and no market-specific rule.
