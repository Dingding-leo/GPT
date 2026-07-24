# Fold-Local Top-3 Score Ensemble

## Hypothesis

A fold-local equal-weight ensemble of the top three candidates selected by the canonical prior-window score reduces fold concentration and passes every BTC/ETH development-stage architecture-freeze and deployment gate.

The economic rationale is that winner-take-all fold selection can amplify estimation noise. The candidate keeps the canonical 27-member grid and selection score, but averages the one-bar-delayed positions of the three highest-scoring candidates in every fold.

Exactly one architecture candidate was searched. `top_2` and `top_4` are predeclared neighbourhood stresses, not alternative candidates. BTC-USDT and ETH-USDT are development markets only; SOL-USDT was not read or used.

## Fixed design

- Provider: OKX public spot data.
- Markets: BTC-USDT and ETH-USDT development evidence.
- Bar: `1Dutc`.
- Baseline: 5 bps one-way exchange fee per unit of absolute aggregate-position turnover.
- Selection/test windows: 730/90 daily bars, non-overlapping tests.
- Candidate grid: momentum 30/90/180 × reversal 2/5/10 × trend weight 0.55/0.70/0.85.
- Architecture: select the top three by the canonical prior-window score, then equally average their delayed positions.
- Costs: fixed-path 5/7.5/10/15 bps.
- Neighbourhood: top-two and top-four ensemble sizes.
- Delay stress: total delays of two and three daily bars at every declared cost.
- Inference: paired non-circular 20-session moving blocks, 2,000 resamples, 95% confidence.

## Exact 5 bps results

| Market | Net return | CAGR | Sharpe | Sortino | Calmar | Max DD | Annual turnover | Profitable folds | Positive-fold concentration |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | +123.947996% | +13.132261% | 0.654874 | 0.991094 | 0.452471 | -29.023429% | 14.321920 | 13/27 | +45.659608% |
| ETH-USDT | +162.645374% | +15.925847% | 0.721629 | 1.066822 | 0.558600 | -28.510267% | 14.331493 | 17/27 | +23.013738% |

## Benchmark-relative inference

| Market | Sharpe delta | Sharpe 95% interval | Calmar delta | Calmar 95% interval |
|---|---:|---:|---:|---:|
| BTC-USDT | -0.087520 | -0.697347 to 0.529414 | 0.071531 | -1.005446 to 0.667716 |
| ETH-USDT | -0.204768 | -0.765697 to 0.404456 | -0.082321 | -1.400933 to 0.586609 |

Both markets fail the predeclared benchmark-relative gate. BTC has a positive point Calmar delta but a negative Sharpe delta and both intervals cross zero. ETH has negative point deltas for both metrics.

## Gate results

| Gate | Joint status |
|---|---|
| `capacity` | **blocked** |
| `development_benchmark_relative_risk_adjusted` | **fail** |
| `execution_delay_robustness` | **fail** |
| `fold_stability` | **fail** |
| `parameter_neighbourhood_stability` | **pass** |
| `prospective_forward_validation` | **blocked** |
| `separate_spread_slippage_impact_latency` | **blocked** |
| `tail_risk` | **pass** |
| `turnover_and_5_7.5_10_15bps_viability` | **pass** |
| `untouched_market_validation` | **blocked** |
| `year_stability` | **pass** |

## Verdict: rejected

Candidate accounting: searched `1`, passed `0`, rejected `1`.

The architecture improves BTC positive-fold concentration below the 50% ceiling and raises ETH performance relative to the canonical adaptive path, but BTC still has only 13 profitable folds out of 27. More importantly, neither market establishes benchmark-relative Sharpe and Calmar superiority under dependence-aware inference. BTC also fails every execution-delay scenario; ETH fails one of eight.

The candidate is not eligible for architecture freeze, untouched-market validation, paper deployment, or live deployment.

## Cost and neighbourhood evidence

| Market | 15 bps net return | 15 bps Sharpe | Top-2 return / Sharpe | Top-4 return / Sharpe |
|---|---:|---:|---:|---:|
| BTC-USDT | +103.944478% | 0.592092 | +132.423973% / 0.691432 | +149.166863% / 0.734014 |
| ETH-USDT | +139.196401% | 0.663804 | +129.734092% / 0.644083 | +145.825514% / 0.685352 |

The cost and ensemble-size neighbourhood gates pass, but they do not override the benchmark, fold and execution-delay failures.

## Provenance

- Source workflow: `30040842607`.
- Source artifact: `8577163034` (`quant-research-source-348-attempt-1`).
- Source artifact SHA-256: `a06f20584f243c4db1420e8ed0b6cacdc13eb11aebddefb72c30cc80176ccd45`.
- Source head: `eea39bc685246209cdb6c0d917fddcc6ef29f34b`.
- Evaluation: 2,385 OOS observations per market, 2020-01-11 through 2026-07-22 UTC.
- Exact snapshot and canonical-return hashes are persisted in `result.json`.

## Reproduction

```bash
python -m reports.research.fold_local_top3_score_ensemble.analysis \
  --artifact-dir /path/to/unpacked/research-artifact \
  --output /tmp/recomputed-top3.json

cmp -s /tmp/recomputed-top3.json \
  reports/research/fold_local_top3_score_ensemble/result.json

pytest -q tests/test_fold_local_top3_score_ensemble_report.py
```

## Limitations

- BTC-USDT and ETH-USDT are development markets and may be used only for architecture design.
- SOL-USDT was not read or used by this analysis and remains prohibited for same-market tuning.
- Top-2 and top-4 are neighbourhood stresses, not separately selected candidate architectures.
- Moving-block resampling creates artificial joins and preserves dependence only within blocks.
- The delayed paths shift observed daily positions and are not executable next-open fills.
- The 7.5/10/15 bps scenarios are aggregate all-in repricings, not measured friction components.
- Capacity and prospective paper evidence remain unavailable.
