# Volume-Weighted Directional Persistence Entry — Terminal Research Report

## Frozen strategy change

The sole candidate preserved the daily 2,160H endpoint-trend exit and changed only entry timing. A cash instrument entered only when its own slow trend was positive and its 720H robust log-quote-volume-weighted return-sign concordance exceeded the instrument-local training q60 boundary. Once long, the participation feature could not force an exit. Decisions were daily at 00:00 UTC, execution was at the next hourly open, and fees were exactly 5 bps one way.

Candidate count: **1**. Parameter-grid variants: **0**.

## Immutable data and sample

| Item | Frozen value |
|---|---|
| Provider | Public confirmed OKX SPOT |
| Markets | BTC-USDT and ETH-USDT independently |
| Bar | 1H |
| Source observations | 43,941 per market |
| Parsed prefix | 43,441 bars |
| Training | `[2,880,17,520)` |
| Development OOS | `[17,520,43,440)` |
| OOS folds | 12 × 2,160H |
| Full scored | `[2,880,43,440)` |
| Later suffix | Unread and unscored |
| Fee | Exactly 0.0005 × absolute position change |

## Frozen training thresholds

| Market | q60 signed-volume concordance |
|---|---:|
| BTC-USDT | 0.005972029 |
| ETH-USDT | -0.023604346 |

No return or PnL statistic selected or altered these boundaries.

## Performance

### Training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | -24.65% | -0.428 | -43.43% | 16 | 0.80% | -131.63 bps |
| BTC-USDT | B1 daily trend | -41.29% | -0.840 | -55.92% | 28 | 1.40% | -159.81 bps |
| ETH-USDT | Candidate | -24.11% | -0.287 | -39.50% | 17 | 0.85% | -100.14 bps |
| ETH-USDT | B1 daily trend | -40.59% | -0.584 | -56.95% | 23 | 1.15% | -168.77 bps |

### Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +141.18% | 1.071 | -30.94% | 23 | 1.15% | +451.96 bps |
| BTC-USDT | B1 daily trend | +119.68% | 0.954 | -26.55% | 45 | 2.25% | +212.75 bps |
| ETH-USDT | Candidate | +140.70% | 0.899 | -44.90% | 10 | 0.50% | +1159.89 bps |
| ETH-USDT | B1 daily trend | +74.52% | 0.646 | -47.77% | 30 | 1.50% | +283.58 bps |

### Full scored sample

| Market | Policy | Net | Sharpe | Max DD | Turnover | Edge/turn |
|---|---|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +81.72% | 0.566 | -43.43% | 39 | +212.54 bps |
| BTC-USDT | B1 daily trend | +28.97% | 0.332 | -55.92% | 73 | +69.85 bps |
| ETH-USDT | Candidate | +82.67% | 0.523 | -44.90% | 27 | +366.53 bps |
| ETH-USDT | B1 daily trend | +3.68% | 0.233 | -56.95% | 53 | +87.28 bps |

## Breadth and uncertainty

| Market | Profitable folds | Profitable years | Positive-fold concentration | Residual Sharpe vs B1 | Mean Δ lower 95% | Sharpe Δ lower 95% |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 6/12 | 3/4 | 32.83% | +0.319 | -7.87% | -0.200 |
| ETH-USDT | 6/12 | 3/4 | 20.92% | +1.142 | -1.93% | -0.028 |

Both markets improved return, Sharpe, turnover and edge per turnover versus B1 at the point-estimate level. ETH also improved drawdown; BTC drawdown worsened. Neither market reached 7/12 profitable folds, and both paired-block lower bounds crossed zero. The exact family therefore fails the preregistered bilateral G1 scorecard.

## Selector diagnosis

| Market | B1-only hours | Return during delayed exposure | Delayed B1 regimes | Never entered before B1 exit | Selector-effect folds | Improved folds vs B1 | Median delay |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 1,920 | -7.11% | 14/22 | 11 | 5/12 | 3/12 | 24H |
| ETH-USDT | 1,080 | -29.91% | 11/15 | 10 | 5/12 | 5/12 | 48H |

The selector never created candidate-only exposure; it only delayed or skipped B1 entries. The omitted exposure was loss-making in aggregate for both markets, which explains the strong point estimates. However, the effect changed returns in only five folds per market and improved arithmetic net performance in only three BTC folds and five ETH folds. This sparse event support explains why dependence-aware uncertainty remained non-positive despite large compounded gains.

Feature activation itself did not materially collapse: the q60 exceedance rate moved from 40.00% in training to 40.65% for BTC and 39.17% for ETH OOS. The problem was not activation-frequency drift; it was insufficient independent economic breadth.

## Failure repaired during execution

The first source-validation pass incorrectly required strictly positive quote volume. The immutable OKX files contain confirmed zero-volume hours; `log1p(0)` is defined and the frozen feature explicitly permits non-negative quote volume. Validation was repaired to require positive OHLC and non-negative quote volume, then the complete experiment was rerun. No rule, threshold, position, fee, comparator, sample boundary or acceptance gate was changed.

A diagnostic counter for B1 regimes that ended before candidate entry was also corrected and the terminal artifact regenerated. Strategy outputs and verdict were unchanged.

## Verdict

```text
reject_exact_volume_weighted_directional_persistence_entry_family
```

No q-level, window, volume transform, robust scaling, clipping, weight, cadence, exit, holding, fee, market-specific or uncertainty rescue is authorised on this consumed development interval. There is no G1 nomination, prospective-paper promotion or live-trading authorisation.

## Remaining blocker

No statistically eligible frozen causal 1H strategy exists.

## Next strategy experiment

Preregister one own-history-only **volume-confirmed trend-onset impulse** architecture that is materially distinct from this persistent entry gate: detect a fixed 168H positive price acceleration coincident with a fixed robust positive 168H quote-volume slope, enter only at the onset of a positive 2,160H slow trend, and apply one fixed minimum hold followed by the base-trend exit. Use one candidate and no parameter grid. This tests whether the timing of participation expansion, rather than the 720H directional sign balance, contains broader forward information.

## Artifact hashes

- `protocol.json`: `32e611ea1c06f29074a4796537e6e6a871fcea2bb782a44c2f827bb0ad971b5e`
- `result.json`: `4aefd55d850aaf9f71fce2f751724bebf96614bd1751838be1e899c88d68d4e5`
- `run_volume_weighted_directional_persistence.py`: `29dcb5e53655fd50f752102b475bf3e295ac7926f3dc53f96de45f7ed7b395f7`
