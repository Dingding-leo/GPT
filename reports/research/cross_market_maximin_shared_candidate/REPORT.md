# Cross-Market Maximin Shared-Candidate Architecture

## Hypothesis

A fold-local cross-market maximin selector chooses one shared parameter tuple that generalizes across BTC-USDT and ETH-USDT and passes every development-stage architecture-freeze gate.

The economic rationale is that market-specific winner-take-all selection can overfit idiosyncratic regimes. The candidate scores all 27 declared parameter tuples separately on the prior 730 sessions of both development markets, chooses the tuple with the highest weaker-market canonical score, and deploys that same tuple in both subsequent 90-session OOS folds.

Exactly one architecture candidate was searched. Mean-score and rank-sum shared selection are predeclared neighbourhood stresses, not separately selected candidates. SOL-USDT was not read or used.

## Fixed design

- Provider: OKX public spot data.
- Markets: BTC-USDT and ETH-USDT development evidence.
- Bar: `1Dutc`.
- Candidate grid: momentum 30/90/180 × reversal 2/5/10 × trend weight 0.55/0.70/0.85.
- Selection: choose one shared candidate per fold by maximizing the minimum BTC/ETH canonical prior-window score.
- Selection/test windows: 730/90 daily bars with non-overlapping OOS tests.
- Execution: long/cash, one-bar delayed positions, continuous market-specific position state.
- Baseline fee: 5 bps one-way per unit of absolute turnover.
- Aggregate fixed-path sensitivities: 7.5, 10 and 15 bps.
- Delay stresses: total delays of two and three daily bars at every declared cost.
- Inference: paired non-circular 20-session moving blocks, 2,000 resamples, 95% confidence.

## Exact 5 bps results

| Market | Net return | CAGR | Sharpe | Sortino | Calmar | Max DD | Annual turnover | Profitable folds |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | +71.626022% | +8.617690% | 0.476595 | 0.699925 | 0.287612 | -29.962928% | 20.869215 | 11/27 |
| ETH-USDT | +74.464719% | +8.890726% | 0.460333 | 0.667452 | 0.278673 | -31.903760% | 16.767451 | 16/27 |

## Benchmark-relative inference

| Market | Sharpe delta | Sharpe 95% interval | Calmar delta | Calmar 95% interval |
|---|---:|---:|---:|---:|
| BTC-USDT | -0.265799 | -0.894675 to +0.368390 | -0.093328 | -1.103523 to +0.387333 |
| ETH-USDT | -0.466065 | -1.014796 to +0.177719 | -0.362248 | -1.665431 to +0.266676 |

Both markets have negative Sharpe and Calmar point deltas versus volatility-targeted long. Every lower confidence bound is negative.

## Gate results

| Gate | Joint status |
|---|---|
| Corrected 5 bps full walk-forward basis | pass |
| Benchmark-relative risk-adjusted evidence | **fail** |
| Fold stability | **fail** |
| Year stability | **fail** |
| 5/7.5/10/15 bps viability | pass |
| Parameter-neighbourhood stability | pass |
| Tail risk | pass |
| Execution-delay robustness | **fail** |
| Separate spread/slippage/impact/latency | blocked |
| Capacity | blocked |
| Untouched-market validation | blocked |
| Prospective forward validation | blocked |
| Overall live eligibility | **false** |

## Verdict: rejected

Candidate accounting: searched `1`, passed `0`, rejected `1`.

The shared maximin rule materially reduces performance relative to both the canonical adaptive path and volatility-targeted long. BTC has only 11 profitable folds and loses 22.07% in the complete 2022 calendar year, breaching the predeclared year-loss ceiling. Both markets fail every dependence-aware benchmark gate and every execution-delay scenario. The candidate is not eligible for architecture freeze, untouched-market validation, paper deployment or live deployment.

## Cost, neighbourhood and tail evidence

| Market | 15 bps return / Sharpe / max DD | Mean-score neighbour return / Sharpe | Rank-sum neighbour return / Sharpe | Strategy ES 5% | Benchmark ES 5% |
|---|---:|---:|---:|---:|---:|
| BTC-USDT | +49.739413% / 0.385064 / -31.745394% | +112.074710% / 0.610944 | +98.094725% / 0.563170 | -2.968655% | -5.921115% |
| ETH-USDT | +56.374642% / 0.395091 / -35.490808% | +181.182311% / 0.736543 | +158.128109% / 0.685781 | -3.446470% | -6.204509% |

Cost, neighbourhood and daily tail-risk gates pass, but they do not override the benchmark, fold, year and delay failures. The neighbourhood results also show that the maximin objective itself is economically inferior to less conservative shared-score aggregations; those alternatives were not promoted after observing the result.

## Provenance

- Source workflow: `30040842607`.
- Source artifact: `8577163034`, `quant-research-source-348-attempt-1`.
- Artifact SHA-256: `a06f20584f243c4db1420e8ed0b6cacdc13eb11aebddefb72c30cc80176ccd45`.
- Source head: `eea39bc685246209cdb6c0d917fddcc6ef29f34b`.
- Evaluation: 2,385 OOS observations per market, 2020-01-11 through 2026-07-22 UTC.
- Exact snapshot and canonical-return hashes are persisted in `result.json`.

## Reproduction

```bash
python reports/research/cross_market_maximin_shared_candidate/analysis.py \
  --artifact-dir /path/to/unpacked/quant-research-source-348-attempt-1 \
  --output /tmp/recomputed-cross-market-maximin.json

cmp -s /tmp/recomputed-cross-market-maximin.json \
  reports/research/cross_market_maximin_shared_candidate/result.json

pytest -q tests/test_cross_market_maximin_shared_candidate_report.py
```

## Limitations

- BTC-USDT and ETH-USDT are development markets and may be used only for architecture design.
- SOL-USDT was not read or used and remains a consumed sealed holdout unavailable for tuning.
- Mean-score and rank-sum rules are neighbourhood stresses, not separately selected architectures.
- Moving-block resampling creates artificial joins and preserves dependence only within 20-session blocks.
- Delay scenarios shift daily positions and are not executable next-open fills.
- The 7.5, 10 and 15 bps scenarios are aggregate all-in repricings, not measured spread, slippage, impact or latency.
- Capacity and prospective paper evidence remain unavailable.
