# Downside-semivariance hysteresis trend-carry 1H experiment

## Strategy change

The sole preregistered candidate in issue #625 preserved immediate entry under each instrument’s own positive 2,160-hour trend. It added a stateful asymmetric risk rule: exit only after the recent 168-hour downside semivariance rose above the training-frozen q80 ratio versus the trailing 2,160-hour downside semivariance, then require cooling below the training-frozen q50 ratio before re-entry while the slow trend remained positive. A non-positive slow trend cleared the risk lock.

Candidate count was `1`; parameter-grid count was `0`; decisions occurred daily at 00:00 UTC; execution was next-open; canonical fees were exactly 5 bps one-way. No cross-sectional information, pairs/spreads, private data, credentials, accounts, orders, leverage, synthetic data or 15-minute data were used.

## Data and sample

- immutable public OKX SPOT confirmed 1H BTC-USDT and ETH-USDT data;
- 43,941 source observations per market; only the first 43,441 bars required through the final OOS payoff were parsed;
- training `[2880,17520)`; development OOS `[17520,43440)`; full scored `[2880,43440)`;
- 12 contiguous OOS folds of 2,160 hours; later suffix remained unread and unscored;
- paired non-circular 168-hour moving-block bootstrap, 5,000 resamples, seed `20260729`.

Frozen training-only boundaries: BTC q50 `0.7529914512239673`, q80 `1.2729954105504169`; ETH q50 `0.7030516429019003`, q80 `1.294158545252833`. No training return or PnL metric selected or modified the rule.

## Training performance

| Market | Policy | Net return | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) | Entries | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | -50.40% | -1.531 | -52.70% | 32 | +1.60% | -202.33 | 16 | 29.02% |
| BTC-USDT | B1 | -41.29% | -0.840 | -55.92% | 28 | +1.40% | -159.81 | 14 | 40.49% |
| ETH-USDT | CANDIDATE | -40.04% | -0.871 | -49.15% | 31 | +1.55% | -140.71 | 15 | 29.02% |
| ETH-USDT | B1 | -40.59% | -0.584 | -56.95% | 23 | +1.15% | -168.77 | 11 | 44.60% |

The candidate lost money in both training markets. BTC was materially worse than B1 in return and Sharpe, while ETH modestly reduced the loss and drawdown but remained economically negative. Training economics were reported only after the architecture was frozen.

## Development-OOS performance

| Market | Policy | Net return | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) | Entries | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | +23.54% | 0.407 | -29.28% | 67 | +3.35% | 46.07 | 33 | 36.86% |
| BTC-USDT | B0 | +111.64% | 0.917 | -22.68% | 203 | +10.15% | 45.31 | 101 | 57.25% |
| BTC-USDT | B1 | +119.68% | 0.954 | -26.55% | 45 | +2.25% | 212.75 | 22 | 57.32% |
| ETH-USDT | CANDIDATE | +20.74% | 0.359 | -46.88% | 48 | +2.40% | 72.11 | 24 | 28.70% |
| ETH-USDT | B0 | +68.02% | 0.618 | -47.30% | 139 | +6.95% | 58.31 | 69 | 49.70% |
| ETH-USDT | B1 | +74.52% | 0.646 | -47.77% | 30 | +1.50% | 283.58 | 15 | 49.72% |

Both markets remained profitable in absolute OOS terms, but the risk rule removed most of the daily trend benchmark’s return. BTC captured only +23.54% versus B1’s +119.68%; ETH captured +20.74% versus +74.52%. BTC also worsened drawdown; ETH improved drawdown by only 0.88 percentage points while sacrificing 53.77 percentage points of compounded return.

## Full scored performance

| Market | Policy | Net return | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) | Entries | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | -38.73% | -0.287 | -59.70% | 99 | +4.95% | -34.22 | 49 | 34.03% |
| BTC-USDT | B1 | +28.97% | 0.332 | -55.92% | 73 | +3.65% | 69.85 | 36 | 51.25% |
| ETH-USDT | CANDIDATE | -27.60% | -0.061 | -51.36% | 79 | +3.95% | -11.40 | 39 | 28.82% |
| ETH-USDT | B1 | +3.68% | 0.233 | -56.95% | 53 | +2.65% | 87.28 | 26 | 47.87% |

The full scored sample was negative for both candidates: BTC `-38.73%` and ETH `-27.60%`. Both had negative full-sample Sharpe and edge per turnover.

## Breadth and uncertainty

| Market | Profitable folds | Profitable years | Positive-fold concentration | Residual Sharpe vs B0 | Residual Sharpe vs B1 | Mean Δ L95 | Sharpe Δ L95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 5/12 | 3/4 | 34.34% | -0.894 | -0.986 | -0.442871 | -1.221698 |
| ETH-USDT | 6/12 | 2/4 | 22.89% | -0.515 | -0.562 | -0.460759 | -1.061693 |

BTC passed only 5/12 profitable folds; ETH passed 6/12 and only 2/4 calendar-year segments. Residual Sharpes were negative against both comparators in both markets. Every paired-bootstrap lower bound was decisively negative.

## Failure mechanism and regime drift

| Market | Ratio median train → OOS | q80 exceedance train → OOS | Risk exits | Negative next-168H windows | B1-only hours | Gross return omitted | Candidate − B1 arithmetic net |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 0.752991 → 0.842832 | 20.00% → 25.19% | 13 | 4/13 | 5304 | +63.77% | -64.87% |
| ETH-USDT | 0.703052 → 0.852896 | 20.00% → 23.24% | 13 | 5/13 | 5448 | +49.56% | -50.46% |

The ratio shifted upward OOS, so the frozen q80 boundary fired more often. That frequency change was not useful: only 4/13 BTC and 5/13 ETH risk exits were followed by a negative next-168-hour market window. The median post-exit 168-hour market return was positive in both markets (`+1.43%` BTC and `+0.16%` ETH).

Because the candidate is a subset of B1 exposure, it created no candidate-only hours. It instead omitted 5,304 BTC hours with `+63.77%` arithmetic gross return and 5,448 ETH hours with `+49.56%`. The downside-semivariance spike was therefore predominantly a **late volatility response inside still-profitable slow trends**, not a forward loss selector. Hysteresis reduced exposure but did not improve turnover efficiency: turnover rose to 67 versus 45 for BTC B1 and 48 versus 30 for ETH B1 because risk exits and re-entries added transitions.

## Repaired discrepancy

The first diagnostic pass accidentally supplied candidate gross return rather than the raw open-to-open market-return series to the omitted-exposure and post-risk-exit decomposition. This produced mechanical zeros in those diagnostic fields. The diagnostic was corrected to use the raw market series and the experiment was rerun. No feature, threshold, position, fee, strategy metric, comparator metric, acceptance gate or verdict changed.

## Verdict

`reject_exact_downside_semivariance_hysteresis_trend_carry_family`

The architecture fails bilateral qualification. No q50/q80 threshold, horizon, state boundary, cadence, execution, fee or market-specific rescue is authorised on the consumed development interval. There is no G1 nomination, prospective-paper promotion or live-trading authorisation.

## Next strategy experiment

Preregister one own-history-only **robust distributed-slope trend estimator** that replaces the fragile two-endpoint 2,160-hour trend sign with a fixed median of twelve non-overlapping 180-hour log-return slopes. Use one candidate, daily next-open decisions and exactly 5 bps one-way fees. The falsifiable objective is to reduce endpoint sensitivity and turnover without adding a post-entry veto, parameter grid or post-hoc asset filtering.
