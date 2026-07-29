# Weekly phase-conditioned trend-carry 1H experiment

## Frozen strategy change

A three-harmonic OLS hour-of-week profile was fitted independently for BTC-USDT and ETH-USDT using training-only next-open hourly log returns observed while each instrument's own 2,160H trend was positive. The 168-hour fitted profile was aggregated into seven next-24H weekday scores. The top two weekdays were frozen as entry opportunities; once long, the policy ignored weekly phase and exited only after a 168H minimum hold when the 2,160H trend became non-positive.

Candidate count: `1`; parameter grid: `0`; preregistration: issue `#617`; parent: `5a0fcc97d1a882f8223656c51f5bb8055f534e38`; fee: exactly `5 bps` one-way.

## Data and sample

| Market | Confirmed source | CSV SHA-256 | Loaded prefix | Training fit support |
|---|---|---|---:|---:|
| BTC-USDT | OKX SPOT 1H artifact 8704977298 | `92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9` | 43,442 | 5,880 |
| ETH-USDT | OKX SPOT 1H artifact 8704978112 | `2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726` | 43,442 | 6,595 |

Warm-up `[0,2880)`, training `[2880,17520)`, development OOS `[17520,43440)`, 12 folds × 2,160H. Later source suffix remained unread and unscored.

## Frozen phase model

| Market | Frozen favourable weekdays | Training weekday-score leader | OOS realised top-two weekdays | Top-two overlap | Pearson / Spearman persistence |
|---|---|---|---|---:|---:|
| BTC-USDT | Sunday, Saturday | Sunday | Wednesday, Monday | 0/2 | +0.367 / +0.071 |
| ETH-USDT | Tuesday, Saturday | Tuesday | Wednesday, Monday | 0/2 | -0.156 / -0.107 |

The frozen top-two weekdays did not overlap the realised OOS top two in either market. ETH's selected weekdays had a mean OOS positive-trend 24H log return of `-0.382%` versus `+0.306%` for unselected weekdays. This is direct phase-selection drift.

## Training performance

| Market | Policy | Net return | Sharpe | Max DD | Turnover | Fees | Edge/turnover | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | -21.76% | -0.315 | -39.27% | 18 | +0.90% | -91.15 bps | +39.34% |
| BTC-USDT | B0 hourly trend | -40.82% | -0.825 | -55.56% | 138 | +6.90% | -31.85 bps | +40.18% |
| BTC-USDT | B1 daily trend | -41.09% | -0.834 | -55.92% | 28 | +1.40% | -158.62 bps | +40.49% |
| ETH-USDT | Candidate | -38.12% | -0.530 | -53.98% | 16 | +0.80% | -218.43 bps | +44.10% |
| ETH-USDT | B0 hourly trend | -46.67% | -0.739 | -57.75% | 88 | +4.40% | -56.17 bps | +45.06% |
| ETH-USDT | B1 daily trend | -40.32% | -0.577 | -56.95% | 23 | +1.15% | -166.79 bps | +44.59% |

## Development-OOS performance

| Market | Policy | Net return | Sharpe | Max DD | Turnover | Fees | Edge/turnover | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +98.25% | 0.865 | -25.14% | 23 | +1.15% | 367.90 bps | +54.81% |
| BTC-USDT | B0 hourly trend | +112.15% | 0.920 | -22.68% | 203 | +10.15% | 45.43 bps | +57.24% |
| BTC-USDT | B1 daily trend | +120.22% | 0.956 | -26.55% | 45 | +2.25% | 213.29 bps | +57.31% |
| ETH-USDT | Candidate | -1.05% | 0.225 | -57.30% | 23 | +1.15% | 134.57 bps | +51.02% |
| ETH-USDT | B0 hourly trend | +68.25% | 0.619 | -47.30% | 139 | +6.95% | 58.41 bps | +49.70% |
| ETH-USDT | B1 daily trend | +74.52% | 0.646 | -47.77% | 30 | +1.50% | 283.58 bps | +49.72% |

## Full scored performance

| Market | Policy | Net return | Sharpe | Max DD | Turnover | Fees | Edge/turnover | Exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +55.10% | 0.455 | -39.27% | 41 | +2.05% | 166.36 bps | +49.23% |
| BTC-USDT | B0 hourly trend | +25.55% | 0.314 | -55.56% | 341 | +17.05% | 14.15 bps | +51.08% |
| BTC-USDT | B1 daily trend | +29.72% | 0.336 | -55.92% | 73 | +3.65% | 70.64 bps | +51.24% |
| ETH-USDT | Candidate | -38.76% | -0.020 | -57.30% | 39 | +1.95% | -10.25 bps | +48.52% |
| ETH-USDT | B0 hourly trend | -10.27% | 0.160 | -57.75% | 227 | +11.35% | 13.99 bps | +48.02% |
| ETH-USDT | B1 daily trend | +4.16% | 0.235 | -56.95% | 53 | +2.65% | 88.14 bps | +47.87% |

## Breadth and uncertainty

| Market | OOS entries | Profitable folds | Profitable years | Positive-fold concentration | Residual Sharpe vs B0 / B1 | Mean delta L95 | Sharpe delta L95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 11 | 6/12 | 3/4 | +40.89% | -0.243 / -0.397 | -0.169754 | -0.458219 |
| ETH-USDT | 11 | 6/12 | 3/4 | +25.76% | -1.005 / -1.179 | -0.406476 | -0.898653 |

BTC improved turnover efficiency, full-sample return and drawdown relative to B1, but failed the preregistered OOS Sharpe, fold breadth, residual-information and uncertainty gates. ETH was the bilateral rejection: negative compounded OOS return, materially worse drawdown, lower edge per turnover, negative residual Sharpe and decisively negative bootstrap bounds.

## Discrepancy repaired

The first diagnostic grouped all OOS weekdays even though the model was fitted only in the positive-2,160H-trend state. The diagnostic was corrected to condition OOS 24H phase returns on the identical positive-trend state, and the entire experiment was rerun. Fitted coefficients, frozen weekdays, positions, PnL, benchmark metrics, breadth, uncertainty and verdict were unchanged; only the phase-persistence diagnostic became regime-consistent.

## Verdict

`reject_exact_weekly_phase_conditioned_trend_carry_family`

No harmonic count, fit regime, target, phase mapping, aggregation window, favourable-day count, trend horizon, holding rule, exit, cadence, timing, fee, market, sizing, comparator or bootstrap rescue is authorised on this consumed development interval. There is no G1 nomination, paper promotion or live-trading authorisation.

## Next strategy experiment

Preregister one materially orthogonal **lagged market-impulse veto for trend carry** architecture. Use the instrument's own positive 2,160H trend as the base rule and one fixed, strictly lagged BTC market-stress feature—defined before development inspection—to delay entries during broad risk-off impulses without forcing recurring exits. Use one candidate, no grid, the same exact 5 bps fee, and bilateral residual/turnover/breadth/bootstrap gates.
