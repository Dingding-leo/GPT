# Canonical 5 bps baseline live-gate inventory

## Hypothesis

The corrected 5 bps full-reselection BTC-USDT / ETH-USDT candidate passes every mandatory paper/live deployment gate.

Economic rationale: a profitable development backtest is not deployment evidence. A candidate must also clear benchmark-relative risk-adjusted performance, fold/year stability, turnover and cost viability, parameter-neighbourhood stability, tail risk, capacity, execution-delay robustness, untouched-market validation, and prospective forward validation.

Canonical signature:

```text
canonical-5bps-live-gate-inventory-v1|markets=BTC-USDT,ETH-USDT|source=PR308-artifact-8566608828|baseline=full-reselection-5bps|costs=5,7.5,10,15bps-fixed-selected-path|candidate_count=1|claim=all-mandatory-paper-live-gates-pass-in-both-markets
```

Exactly one joint candidate was evaluated. No strategy formula, candidate grid, fee, cost scenario, benchmark, market subset, threshold, or acceptance rule was selected after reading the result.

## Source and scope

- Canonical implementation owner: PR #308 / issue #306.
- Source workflow: `30014704624`.
- Source artifact: `8566608828`, `quant-research-source-2037-attempt-1`.
- Artifact SHA-256: `ab0846180ff5b9397de26de8ca8d728ad237be00bdb92ba1612ef6ba243fc149`.
- Source head: `0d9c098f6408f4510bbefb95633e3d695f30dde3`.
- Markets: OKX spot BTC-USDT and ETH-USDT, `1Dutc`.
- Evaluation: 2020-01-11 through 2026-07-22 UTC, 2,385 OOS observations, 27 folds, 27 candidates per selection window.
- Baseline: full candidate reselection at 5 bps one-way exchange fee.
- Cost sensitivities: fixed-selected-path repricing at 7.5, 10, and 15 bps; these are not measured spread, slippage, impact, or latency.

## Exact 5 bps metrics

| Metric | BTC-USDT | ETH-USDT |
|---|---:|---:|
| Gross total return | +155.43% | +122.80% |
| Net total return | +142.09% | +110.57% |
| Net CAGR | 14.49% | 12.07% |
| Annualized arithmetic mean | 16.13% | 14.55% |
| Sharpe | 0.707 | 0.579 |
| Sortino | 1.087 | 0.852 |
| Calmar | 0.510 | 0.414 |
| Maximum drawdown | -28.41% | -29.18% |
| Current drawdown | -20.46% | -20.87% |
| Longest underwater duration | 784 bars | 792 bars |
| 5% expected shortfall | -2.84% | -3.34% |
| Total absolute turnover | 107.33 | 113.05 |
| Annualized turnover | 16.43 | 17.30 |
| Exchange-fee sum | 5.37% | 5.65% |
| Average absolute exposure | 26.14% | 21.22% |
| Position adjustments | 1,316 | 1,416 |
| Holding episodes | 71 | 97 |
| Completed episode win rate | 39.44% | 56.25% |
| Completed episode profit factor | 2.237 | 2.016 |
| Profitable months | 29 / 79 | 33 / 79 |
| Profitable completed years | 3 / 5 | 3 / 5 |
| Profitable folds | 12 / 27 | 17 / 27 |
| Best fold | +83.27% | +52.58% |
| Worst fold | -23.81% | -25.16% |

The volatility-targeted-long benchmark Sharpe/Calmar values were `0.742/0.381` for BTC and `0.926/0.641` for ETH. BTC therefore fails the Sharpe comparison, while ETH fails both Sharpe and Calmar.

## Absolute cost sensitivity

| Market | Cost | Total return | CAGR | Sharpe | Max drawdown |
|---|---:|---:|---:|---:|---:|
| BTC-USDT | 5 bps | +142.09% | 14.49% | 0.707 | -28.41% |
| BTC-USDT | 7.5 bps | +135.68% | 14.02% | 0.689 | -28.69% |
| BTC-USDT | 10 bps | +129.45% | 13.55% | 0.671 | -29.10% |
| BTC-USDT | 15 bps | +117.46% | 12.62% | 0.635 | -29.91% |
| ETH-USDT | 5 bps | +110.57% | 12.07% | 0.579 | -29.18% |
| ETH-USDT | 7.5 bps | +104.71% | 11.59% | 0.562 | -29.31% |
| ETH-USDT | 10 bps | +99.01% | 11.11% | 0.545 | -29.54% |
| ETH-USDT | 15 bps | +88.08% | 10.15% | 0.511 | -30.10% |

The selected path remains positive under 15 bps fixed-path repricing. This does not replace a component-level execution model.

## Deployment gates

| Mandatory gate | Joint status | Reason |
|---|---|---|
| Corrected 5 bps full reselection | Pass | Both artifacts use 5 bps inside 27-candidate fold selection. |
| Benchmark-relative risk-adjusted evidence | Fail | BTC Sharpe trails benchmark; ETH Sharpe and Calmar trail benchmark. |
| Fold stability | Fail | BTC has only 12/27 profitable folds and fails the repository fold gate. |
| Year stability | Fail | BTC's 2022 completed-year return is below the predeclared -20% floor. |
| Turnover and 5/7.5/10/15 bps viability | Pass | Annualized turnover is below 20 and 15 bps net return/Sharpe remain positive. |
| Parameter-neighbourhood stability | Pass | All declared perturbations retain positive total return, Sharpe, and drawdown above -40%. |
| Tail risk | Pass | Both have shallower drawdown and less severe 5% ES than the unscaled volatility benchmark. |
| Separate spread/slippage/impact/latency evidence | Blocked | These components are not separately measured or modelled. |
| Capacity | Blocked | No volume-participation or market-impact capacity gate is persisted. |
| Execution-delay robustness | Blocked | No predeclared multi-delay candidate evidence exists for the 5 bps architecture. |
| Untouched-market validation | Blocked | BTC and ETH are development markets; no sealed market has been evaluated. |
| Prospective forward validation | Blocked | No paper-forward observation window has been completed. |

## Verdict: rejected — not live eligible

```text
Candidates searched: 1
Passed:              0
Rejected:            1
Live eligible:       false
```

The corrected 5 bps baseline is profitable, survives fixed-path cost repricing through 15 bps, and has useful tail-risk control. It nevertheless fails benchmark-relative evidence and joint fold/year stability, while five mandatory deployment gates remain untested. It is not paper/live eligible.

## Limitations

The 7.5/10/15 bps scenarios reprice the selected 5 bps path rather than repeat candidate selection. BTC and ETH are development markets. The inventory is a research-layer audit of PR #308 artifacts and does not change the formal report schema owned by issue #306. Position changes are not exchange orders or fills. No account, credential, order, leverage, or fund access was used.
