# Volume-Confirmed Trend-Onset Impulse — Terminal Research Report

## Frozen strategy change

The sole candidate changed entry timing and minimum-hold behaviour around the first 168 hours of each positive 2,160H trend regime. At daily 00:00 UTC decisions, entry required a positive trailing 168H return, positive acceleration versus the preceding 168H return, and a positive robust quote-volume slope computed from seven 24H medians of trailing `log1p(volume_quote)`. A qualifying entry executed at the next open, held for at least 168H, and thereafter exited only when the daily 2,160H trend became non-positive. Fees were exactly 5 bps one way.

Candidate count: **1**. Parameter-grid variants: **0**. No fitted threshold or market-specific rule was used.

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
| OOS breadth | 12 contiguous 2,160H folds plus calendar years |
| Full scored | `[2,880,43,440)` |
| Later suffix | Unread and unscored |
| Fee | Exactly `0.0005 × absolute position change` |

## Performance

### Training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | -20.34% | -0.320 | -41.89% | 15 | +0.75% | -104.03 bps |
| BTC-USDT | B1 daily trend | -41.29% | -0.840 | -55.92% | 28 | +1.40% | -159.81 bps |
| BTC-USDT | B0 hourly trend | -41.02% | -0.831 | -55.56% | 138 | +6.90% | -32.09 bps |
| ETH-USDT | Candidate | -15.00% | -0.136 | -31.71% | 10 | +0.50% | -73.83 bps |
| ETH-USDT | B1 daily trend | -40.59% | -0.584 | -56.95% | 23 | +1.15% | -168.77 bps |
| ETH-USDT | B0 hourly trend | -46.84% | -0.744 | -57.75% | 88 | +4.40% | -56.53 bps |

### Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +81.06% | 0.780 | -27.90% | 21 | +1.05% | +357.13 bps |
| BTC-USDT | B1 daily trend | +119.68% | 0.954 | -26.55% | 45 | +2.25% | +212.75 bps |
| BTC-USDT | B0 hourly trend | +111.64% | 0.917 | -22.68% | 203 | +10.15% | +45.31 bps |
| ETH-USDT | Candidate | +65.52% | 0.603 | -44.97% | 16 | +0.80% | +504.24 bps |
| ETH-USDT | B1 daily trend | +74.52% | 0.646 | -47.77% | 30 | +1.50% | +283.58 bps |
| ETH-USDT | B0 hourly trend | +68.02% | 0.618 | -47.30% | 139 | +6.95% | +58.31 bps |

### Full scored sample

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +44.24% | 0.409 | -41.89% | 36 | +1.80% | +164.98 bps |
| BTC-USDT | B1 daily trend | +28.97% | 0.332 | -55.92% | 73 | +3.65% | +69.85 bps |
| BTC-USDT | B0 hourly trend | +24.82% | 0.310 | -55.56% | 341 | +17.05% | +13.98 bps |
| ETH-USDT | Candidate | +40.69% | 0.385 | -44.97% | 26 | +1.30% | +281.90 bps |
| ETH-USDT | B1 daily trend | +3.68% | 0.233 | -56.95% | 53 | +2.65% | +87.28 bps |
| ETH-USDT | B0 hourly trend | -10.68% | 0.158 | -57.75% | 227 | +11.35% | +13.79 bps |

## Breadth and uncertainty

| Market | Profitable folds | Profitable years | Positive-fold concentration | Residual Sharpe vs B1 | Mean Δ lower 95% | Sharpe Δ lower 95% |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 6/12 | 3/4 | 42.40% | -0.655 | -22.51% | -0.619 |
| ETH-USDT | 6/12 | 3/4 | 23.24% | -0.107 | -19.66% | -0.451 |

Both markets produced positive development-OOS returns and lower turnover than B1, but neither improved B1 return or Sharpe. Both reached only 6/12 profitable folds, had negative residual Sharpe versus B1, and had decisively non-positive dependence-aware lower confidence bounds. BTC also worsened maximum drawdown. The bilateral scorecard therefore rejects the exact family.

## Failure mechanism

| Market | OOS base onsets | Qualified | Missed | Median delay | B1-only hours | Return in omitted B1 exposure | Candidate-only hours | Return in forced-hold exposure | Fee saving vs B1 | Arithmetic net delta vs B1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 22 | 10 | 12 | 24H | 2,280 | +18.21% | 240 | -3.73% | +1.20% | -20.74% |
| ETH-USDT | 15 | 8 | 7 | 36H | 600 | -5.07% | 216 | -10.16% | +0.70% | -4.40% |

The candidate did not behave as a pure entry filter because the predeclared 168H minimum hold created candidate-only exposure whenever the base trend reversed soon after entry. An initial entry-only diagnostic would therefore have been incomplete. The terminal reproducer explicitly decomposes both directions of exposure and asserts the exact identity `candidate-only market return − B1-only market return − incremental fees = candidate minus B1 arithmetic net` to `1e-12`.

- **BTC:** the filter omitted 2,280 hours of B1 exposure that earned +18.21% arithmetically, while forced-hold exposure lost 3.73%. Lower fees recovered only 1.20%, leaving a −20.74% arithmetic delta. The selector systematically removed profitable continuation.
- **ETH:** omitted B1 exposure lost 5.07%, which was helpful, but forced-hold exposure lost 10.16%; the 0.70% fee saving was insufficient, leaving a −4.40% arithmetic delta. The minimum hold reversed most of the benefit from skipped weak entries.

Event support remained modest: BTC qualified 10 of 22 OOS onsets and ETH 8 of 15. The strategy changed returns in 10 BTC folds and 7 ETH folds, but improved arithmetic net performance in only 4 and 5 folds respectively. The positive compounded returns were dominated by a few long continuation episodes rather than broad, independently repeated onset information.

## Feature drift

| Market | Joint confirmation, train → OOS | Positive volume slope, train → OOS | Positive trailing return, train → OOS |
|---|---:|---:|---:|
| BTC-USDT | 8.03% → 14.91% | 44.92% → 50.93% | 44.75% → 53.33% |
| ETH-USDT | 8.52% → 12.59% | 44.75% → 49.35% | 46.89% → 49.35% |

Activation increased OOS rather than collapsing. The rejection is economic calibration failure: positive acceleration plus expanding volume did not distinguish durable trend onset from short-lived rebounds, and the fixed minimum hold amplified false positives.

## Verdict

```text
reject_exact_volume_confirmed_trend_onset_impulse_family
```

No onset window, price horizon, acceleration definition, volume transformation, block construction, slope threshold, minimum hold, cadence, exit, fee, market-specific or same-interval rescue is authorised. There is no G1 nomination, prospective-paper promotion or live-trading authorisation.

## Remaining blocker

No statistically eligible frozen causal 1H strategy exists.

## Next strategy experiment

Preregister one own-history-only **trend-state survival calibration** architecture: estimate, from training only, the empirical survival probability that a newly positive 2,160H daily trend remains positive for the next 168H using a fixed small set of causal onset covariates (trend margin scaled by trailing downside deviation, 168H return, and robust volume slope), then enter only when a conservative lower credible bound clears the exact two-way fee hurdle. Use one fixed Bayesian model, one candidate, no hyperparameter grid, explicit minimum state support, and no forced minimum hold. This directly repairs the present failure by forecasting persistence rather than treating all positive acceleration/volume impulses as equivalent.

## Artifact hashes

- `protocol.json`: `af8dadede847678d99c5d365c6d4e6d759a00841b3b085ad9c805b8e247ed557`
- `result.json`: `7f273e54e59d16484e103bf44d786e237812804fe9b09f98fa0ca75e500bfb6b`
- `run_volume_confirmed_trend_onset.py`: `85556e9b2984baa15a4877c79ef530e7b84fa5f3383ba745c399ff62ba95749d`
