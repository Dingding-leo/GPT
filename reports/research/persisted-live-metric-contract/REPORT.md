# Canonical 5 bps path-derived live-readiness metrics

## Hypothesis

The verified canonical 5 bps walk-forward CSV contains sufficient persisted evidence to independently reconstruct every **path-derived** live-readiness metric required by issue #306 for both BTC-USDT and ETH-USDT.

Economic rationale: architecture freeze and untouched-market validation should not begin while core turnover, holding, calendar, exposure and drawdown diagnostics depend on an unpublished notebook or unavailable execution data. This test asks whether those metrics can be derived deterministically from the current persisted selected path; it does not claim that the production report already persists them or that the strategy passes deployment gates.

Exactly one joint evidence candidate was tested. No strategy, fee, parameter family, market subset, metric definition or acceptance threshold was changed after observing the result.

## Source and fixed definitions

- Provider: OKX spot.
- Markets: BTC-USDT and ETH-USDT development evidence.
- Timeframe: `1Dutc`.
- Canonical baseline: full 27-candidate reselection at 5 bps one-way exchange fee.
- Workflow: `30033465689`.
- Artifact: `8574277655`, `quant-research-source-2350-attempt-1`.
- Artifact SHA-256: `c80382a4f310828d1bba27f8cbecd41379d379d7dd1f3244434fb57f4d574c72`.
- Persisted source commit: `ce3eae5c0eeb663e87f523c9fe540b33638515eb`.
- Position-adjustment threshold: `1e-12` absolute turnover.
- Holding episode: contiguous bars with absolute executed position above the threshold.
- Completed episode return: compounded net return from the first active bar through the first subsequent cash bar, including entry and exit fee.
- Holding duration counts active-position bars only.
- Bar hit rate uses nonzero net-return bars, matching the repository convention.
- Calendar returns are compounded; the first and last incomplete periods are explicitly labelled partial.

## Verdict: supported sub-gate, strategy still rejected for live use

All required path-derived metrics were reconstructed from the verified CSV in both markets. Candidate accounting: searched `1`, passed `1`, rejected `0`.

Before accepting the sub-gate, the executable independently recomputed and reconciled every formal aggregate value used in this report against the CSV. Fold stability uses the producer's complete persisted verdict, including positive-fold concentration, rather than only counting profitable folds.

This closes only the **reconstructability** question. The formal production JSON/Markdown still does not persist the complete issue #306 metric contract, and the strategy remains not live eligible.

## Exact canonical 5 bps performance

| Metric | BTC-USDT | ETH-USDT |
|---|---:|---:|
| Net total return | +142.09% | +110.57% |
| Net CAGR | 14.49% | 12.07% |
| Sharpe | 0.707 | 0.579 |
| Sortino | 1.087 | 0.852 |
| Calmar | 0.510 | 0.414 |
| Maximum drawdown | -28.41% | -29.18% |
| Annualized turnover | 16.43 | 17.30 |
| Profitable folds | 12/27 | 17/27 |

## Reconstructed path diagnostics

| Metric | BTC-USDT | ETH-USDT |
|---|---:|---:|
| Total absolute turnover | 107.3271 | 113.0521 |
| Position adjustments | 1,316 | 1,416 |
| Annualized adjustments | 201.40 | 216.70 |
| Holding episodes | 71 | 97 |
| Completed / open episodes | 71 / 0 | 96 / 1 |
| Average holding duration | 17.54 bars | 13.61 bars |
| Median holding duration | 4 bars | 3 bars |
| Maximum holding duration | 149 bars | 84 bars |
| Completed-episode win rate | 38.03% | 56.25% |
| Completed-episode profit factor | 2.230 | 2.008 |
| Nonzero-bar hit rate | 47.49% | 48.73% |
| Average absolute exposure | 26.14% | 21.22% |
| Current absolute exposure | 0.00% | 61.08% |
| Maximum absolute exposure | 98.47% | 95.67% |
| Profitable / losing / flat months | 29 / 35 / 15 | 33 / 29 / 17 |
| Profitable / losing years | 4 / 3 | 4 / 3 |
| Current drawdown | -20.46% | -20.87% |
| Current underwater duration | 582 bars | 343 bars |
| Longest underwater duration | 784 bars | 792 bars |

The yearly evidence is not stable enough for live eligibility. Both markets have three losing calendar years when the partial first and latest years are retained and labelled. BTC also has only 12 profitable OOS folds out of 27.

## Live-gate status

| Gate | Status |
|---|---|
| Corrected 5 bps full reselection | Pass |
| Path-derived metric reconstructability | Pass |
| Formal persisted metric contract | **Fail** |
| Benchmark-relative risk-adjusted evidence | **Fail** |
| Fold stability | **Fail** |
| Year stability | **Fail** |
| 5/7.5/10/15 bps selected-path viability | Pass |
| Parameter-neighbourhood stability | Pass |
| Tail risk | Pass |
| Execution-delay robustness | **Fail** |
| Separate spread/slippage/impact/latency | Blocked |
| Capacity | Blocked |
| Untouched-market validation | Blocked |
| Prospective forward validation | Blocked |
| Overall live eligibility | **False** |

## Limitations

Holding episodes are research constructs derived from target exposure, not exchange orders or fills. The current evidence does not model spread, slippage, market impact, latency, capacity or partial fills. BTC-USDT and ETH-USDT remain development markets. Passing this sub-gate must not be interpreted as permission to tune further on them or begin live execution.
