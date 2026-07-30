# Four-phase daily trend ensemble — terminal evidence

## Frozen strategy change

At completed 00:00, 06:00, 12:00 and 18:00 UTC bars, update only that phase's own-instrument 2,160H endpoint-trend state. Execute at the next hourly open with exposure equal to the fraction of four positive phase states, restricted to `0, 0.25, 0.5, 0.75, 1`. Exactly 5 bps one way is charged on every absolute exposure change.

```text
family_id       four-phase-daily-trend-ensemble-1h-v1
issue           #688
candidate_count 1
parameter_grid  0
research_parent 5a0fcc97d1a882f8223656c51f5bb8055f534e38
verdict         reject_exact_four_phase_daily_trend_ensemble_family
```

## Immutable data and sample

| Item | Frozen specification |
|---|---|
| Provider | Public confirmed OKX SPOT |
| Markets | BTC-USDT and ETH-USDT independently |
| Bar | 1H only |
| Source observations | 43,941 per market |
| Parsed prefix | 43,441 bars |
| Training | `[2,880,17,520)` |
| Development OOS | `[17,520,43,440)` |
| Full scored | `[2,880,43,440)` |
| OOS breadth | 12 contiguous 2,160H folds plus calendar years |
| Uncertainty | 5,000 paired non-circular 168H moving-block resamples |
| Fee | Exactly 5 bps one way |

## Training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn | Mean exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | -40.70% | -0.842 | -55.27% | 29.50 | +1.48% | -149.31 bps | 0.4020 |
| BTC-USDT | B0 hourly | -41.02% | -0.831 | -55.56% | 138.00 | +6.90% | -32.09 bps | 0.4018 |
| BTC-USDT | B1 daily | -41.29% | -0.840 | -55.92% | 28.00 | +1.40% | -159.81 bps | 0.4049 |
| ETH-USDT | Candidate | -43.36% | -0.660 | -58.67% | 22.25 | +1.11% | -196.29 bps | 0.4500 |
| ETH-USDT | B0 hourly | -46.84% | -0.744 | -57.75% | 88.00 | +4.40% | -56.53 bps | 0.4506 |
| ETH-USDT | B1 daily | -40.59% | -0.584 | -56.95% | 23.00 | +1.15% | -168.77 bps | 0.4460 |

## Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn | Mean exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +127.76% | 0.993 | -23.31% | 42.00 | +2.10% | +236.15 bps | 0.5728 |
| BTC-USDT | B0 hourly | +111.64% | 0.917 | -22.68% | 203.00 | +10.15% | +45.31 bps | 0.5725 |
| BTC-USDT | B1 daily | +119.68% | 0.954 | -26.55% | 45.00 | +2.25% | +212.75 bps | 0.5732 |
| ETH-USDT | Candidate | +78.28% | 0.663 | -44.32% | 30.75 | +1.54% | +282.54 bps | 0.4983 |
| ETH-USDT | B0 hourly | +68.02% | 0.618 | -47.30% | 139.00 | +6.95% | +58.31 bps | 0.4970 |
| ETH-USDT | B1 daily | +74.52% | 0.646 | -47.77% | 30.00 | +1.50% | +283.58 bps | 0.4972 |

## Full scored

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn | Mean exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +35.05% | 0.362 | -55.27% | 71.50 | +3.57% | +77.11 bps | 0.5112 |
| BTC-USDT | B0 hourly | +24.82% | 0.310 | -55.56% | 341.00 | +17.05% | +13.98 bps | 0.5108 |
| BTC-USDT | B1 daily | +28.97% | 0.332 | -55.92% | 73.00 | +3.65% | +69.85 bps | 0.5125 |
| ETH-USDT | Candidate | +0.99% | 0.219 | -58.67% | 53.00 | +2.65% | +81.52 bps | 0.4809 |
| ETH-USDT | B0 hourly | -10.68% | 0.158 | -57.75% | 227.00 | +11.35% | +13.79 bps | 0.4803 |
| ETH-USDT | B1 daily | +3.68% | 0.233 | -56.95% | 53.00 | +2.65% | +87.28 bps | 0.4787 |

## Breadth and uncertainty

| Market | Profitable folds | Profitable years | Folds/years improved vs B1 | Residual Sharpe | Mean Δ 95% interval | Sharpe Δ 95% interval |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 5/12 | 3/4 | 6/12; 2/4 | 0.305 | [-2.72%, +5.17%] | [-0.075, 0.158] |
| ETH-USDT | 6/12 | 3/4 | 4/12; 2/4 | 0.153 | [-4.06%, +5.63%] | [-0.088, 0.130] |

## Acceptance gates

**BTC-USDT: rejected.** Failed gates: `positive_mean_delta_lower_95`, `positive_sharpe_delta_lower_95`, `profitable_folds_at_least_7`.

**ETH-USDT: rejected.** Failed gates: `edge_per_turnover_at_least_b1`, `positive_mean_delta_lower_95`, `positive_sharpe_delta_lower_95`, `profitable_folds_at_least_7`, `turnover_no_greater_b1`.

## Failure mechanism

### BTC-USDT

- Candidate versus B1 compounded OOS return: +127.76% versus +119.68%; Sharpe 0.993 versus 0.954; drawdown -23.31% versus -26.55%; turnover 42.00 versus 45.00.
- Fractional exposure existed for only 1,212 hours (4.68% of OOS), across 43 episodes. Largest duration concentration was 8.42%.
- Candidate-minus-B1 arithmetic net delta was +3.44%: exposure-timing contribution +3.29% and incremental fees -0.15%.
- Profitable folds: 5/12; folds improved versus B1: 6/12. Both dependence-aware lower bounds remained below zero.

### ETH-USDT

- Candidate versus B1 compounded OOS return: +78.28% versus +74.52%; Sharpe 0.663 versus 0.646; drawdown -44.32% versus -47.77%; turnover 30.75 versus 30.00.
- Fractional exposure existed for only 781 hours (3.01% of OOS), across 32 episodes. Largest duration concentration was 6.91%.
- Candidate-minus-B1 arithmetic net delta was +1.81%: exposure-timing contribution +1.84% and incremental fees +0.04%.
- Profitable folds: 6/12; folds improved versus B1: 4/12. Both dependence-aware lower bounds remained below zero.

The phase ensemble improved aggregate point estimates in both markets, but the effect was confined to brief disagreement intervals around slow-trend crossings. It did not repair the base strategy's fold breadth. BTC passed every benchmark-relative point gate but failed fold breadth and both uncertainty gates. ETH additionally used 0.75 more turnover than B1 and produced slightly lower edge per turnover.

### Transition-direction repair

The initial transition diagnostic pooled phase additions and cuts even though their forward-return meanings are opposite. Terminal evidence separates 0-to-1 additions from 1-to-0 cuts, adds an independent four-phase position reconstruction, and reports fractional-state episode concentration. No phase state, exposure, fee, return, benchmark, bootstrap result, gate or verdict changed.

The repaired diagnostic shows that phase additions and cuts have opposite economic meanings and must not be pooled. The strategy positions were also reconstructed independently from four separate phase-held binary series. Two complete executions produced byte-identical `result.json` output.

## Verdict

```text
reject_exact_four_phase_daily_trend_ensemble_family
```

No same-interval phase count, phase hours, trend horizon, exposure mapping, cadence, fee or market-specific rescue is authorised. No G1 nomination, paper promotion or live-trading authorisation results.

**Remaining blocker:** Temporal phase diversification improves bilateral aggregate point estimates, but it changes exposure during only a small fraction of hours and does not create sufficient fold breadth or dependence-aware evidence. ETH also incurs slightly more turnover and slightly lower edge per turnover than B1.

**Next experiment:** One own-history-only directional-movement trend-quality architecture: retain immediate 2,160H trend entry, then use fixed 720H Wilder-style positive versus negative directional movement and a latest-versus-prior 168H directional-balance change to permit a reversible 50% risk state; one candidate, no fitted threshold, no grid or market-specific rule.
