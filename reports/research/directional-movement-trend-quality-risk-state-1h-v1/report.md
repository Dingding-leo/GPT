# Directional-movement trend-quality risk state — terminal evidence

## Frozen architecture

```text
family_id          directional-movement-trend-quality-risk-state-1h-v1
candidate_count    1
parameter_grid     0
bar                1H
execution          next hourly open
fee                exactly 5 bps one way
markets            BTC-USDT and ETH-USDT independently
```

The candidate retains the daily 2,160H endpoint-trend benchmark. Inside an already-positive trend it moves from full exposure to 50% when current 720H Wilder directional balance is negative and its latest 168H mean is below the preceding 168H mean. It restores full exposure only when the current balance is positive and the latest 168H mean is above the preceding mean. Ambiguous states retain the prior exposure; a non-positive base trend forces cash.

No fitted threshold, grid, exogenous input, market-specific rule, leverage, cross-sectional operation, pairs/spreads, synthetic data, credentials, accounts, orders or 15m data was used.

## Immutable data and sample

| Item | Frozen value |
|---|---|
| Provider | Public confirmed OKX SPOT |
| BTC source | artifact `8704977298`; SHA-256 `92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9` |
| ETH source | artifact `8704978112`; SHA-256 `2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726` |
| Parsed observations | first 43,441 confirmed contiguous 1H bars per market |
| Training | `[2,880,17,520)` |
| Development OOS | `[17,520,43,440)` |
| Full scored | `[2,880,43,440)` |
| Breadth | 12 contiguous 2,160H folds plus calendar years |
| Uncertainty | 5,000 paired non-circular 168H moving-block resamples; seed `20260730` |
| Later suffix | unread and unscored |

## Performance

### Training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC | CANDIDATE | -28.71% | -0.668 | -41.79% | 30.00 | 1.50% | -94.73 |
| BTC | B1 | -41.29% | -0.840 | -55.92% | 28.00 | 1.40% | -159.81 |
| ETH | CANDIDATE | -31.58% | -0.674 | -40.30% | 26.50 | 1.33% | -118.57 |
| ETH | B1 | -40.59% | -0.584 | -56.95% | 23.00 | 1.15% | -168.77 |

### Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC | CANDIDATE | +112.68% | 1.076 | -23.20% | 52.50 | 2.63% | 164.46 |
| BTC | B0 | +111.64% | 0.917 | -22.68% | 203.00 | 10.15% | 45.31 |
| BTC | B1 | +119.68% | 0.954 | -26.55% | 45.00 | 2.25% | 212.75 |
| ETH | CANDIDATE | +84.48% | 0.807 | -37.46% | 39.00 | 1.95% | 195.85 |
| ETH | B0 | +68.02% | 0.618 | -47.30% | 139.00 | 6.95% | 58.31 |
| ETH | B1 | +74.52% | 0.646 | -47.77% | 30.00 | 1.50% | 283.58 |

### Full scored

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC | CANDIDATE | +51.62% | 0.472 | -41.79% | 82.50 | 4.12% | 70.21 |
| BTC | B1 | +28.97% | 0.332 | -55.92% | 73.00 | 3.65% | 69.85 |
| ETH | CANDIDATE | +26.23% | 0.318 | -40.30% | 65.50 | 3.28% | 68.64 |
| ETH | B1 | +3.68% | 0.233 | -56.95% | 53.00 | 2.65% | 87.28 |

## Breadth and uncertainty

| Market | Profitable folds | Profitable years | Improved vs B1 | Positive-fold concentration | Residual Sharpe | Mean Δ 95% | Sharpe Δ 95% |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 4/12 | 2/4 | 5/12 folds; 2/4 years | 30.10% | -0.270 | [-16.34%, +8.83%] | [-0.255, +0.465] |
| ETH-USDT | 6/12 | 3/4 | 6/12 folds; 2/4 years | 31.92% | -0.164 | [-24.10%, +17.49%] | [-0.224, +0.527] |

## Failure mechanism

### BTC-USDT

- Eligible risk-state frequency: `34.67%`; effective risk/recovery transitions: `16 / 8`.
- Risk transitions were followed by mean returns of `+0.94%` over 24H and `+0.41%` over 168H; the 168H positive share was `56.25%`.
- The half state occupied `7,345` hours and carried `+18.05%` arithmetic market return, with conditional Sharpe `0.487` versus `2.054` at full exposure.
- Scaling removed `3,672.5` full-exposure-equivalent hours and `+9.02%` arithmetic market return, while incremental fees were `+0.375%`. Exact arithmetic candidate-minus-B1 delta was `-9.40%`.
- Half-state breadth was `17` episodes, `10` positive and `7` negative; largest duration concentration was `14.70%`.

### ETH-USDT

- Eligible risk-state frequency: `38.12%`; effective risk/recovery transitions: `20 / 9`.
- Risk transitions were followed by mean returns of `-0.08%` over 24H and `-1.47%` over 168H; the 168H positive share was `40.00%`.
- The half state occupied `7,776` hours and carried `+16.49%` arithmetic market return, with conditional Sharpe `0.284` versus `2.011` at full exposure.
- Scaling removed `3,888.0` full-exposure-equivalent hours and `+8.24%` arithmetic market return, while incremental fees were `+0.450%`. Exact arithmetic candidate-minus-B1 delta was `-8.69%`.
- Half-state breadth was `20` episodes, `13` positive and `7` negative; largest duration concentration was `20.68%`.

BTC improved Sharpe and drawdown but underperformed B1 on compounded return, turnover and edge per turnover. Its risk transitions were followed by positive continuation, so the state reduced exposure too early.

ETH improved compounded return, Sharpe and drawdown, but this was sequencing-driven: arithmetic return versus B1 was lower after incremental fees. It failed turnover, efficiency, fold breadth, residual-Sharpe and both uncertainty gates.

## Diagnostic repair and reproducibility

The initial diagnostic counted a positive-trend onset that happened to satisfy the recovery inequality as a recovery transition. Terminal evidence counts effective transitions only when the risk/recovery action changes an already-positive trend exposure, separates unconditional from eligible trigger frequencies, and attributes turnover at the actual next-open execution index. No signal, exposure, fee, return, benchmark, bootstrap result, gate or verdict changed.

Two complete executions produced byte-identical results:

```text
result.json SHA-256   52fc64ac8b39b074e5a8eb51ac38bd9f1a47991f0fcbfec4dd6734b8fd63d5a6
protocol.json SHA-256 39edf333366a1cc1fce753c94b547dee29d394cbe5c6930c03ce94d6ec1e7771
```

## Verdict

```text
reject_exact_directional_movement_trend_quality_risk_state_family
```

Failure on either market rejects the exact family. No same-interval change to the Wilder initialisation, smoothing horizon, balance definition, 168H comparison, exposure fraction, hysteresis, cadence, fee or market-specific treatment is authorised. No G1 nomination, paper promotion or live-trading authorisation results.

**Remaining blocker:** directional-movement deterioration identifies lower-quality exposure, particularly in ETH, but the lower-quality state still carries positive trend return. Recurrent partial-risk transitions remove positive carry and consume turnover; the relationship lacks bilateral breadth and dependence-aware support.

**Next experiment:** one own-history-only trend-onset participation-decay architecture. Enter the unchanged 2,160H positive trend immediately, then permit a single irreversible exit only when the latest 168H positive directional-movement sum falls below one half of its maximum since onset while the completed close remains below the onset close. No re-entry until a new onset; one candidate, no fitted threshold, grid, exogenous input or market-specific rule.
