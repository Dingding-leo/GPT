# Benchmark-Relative OOS Fold Breadth

## Hypothesis

BTC-USDT and ETH-USDT should each outperform the persisted volatility-targeted-long benchmark in more than half of their complete 90-session rolling out-of-sample folds. The hypothesis passes only if the 95% moving-block-bootstrap lower bound for the outperformance share is strictly above 50% in both development markets.

Economic rationale: aggregate benchmark-relative performance can be dominated by a small number of exceptional deployment windows. A credible adaptive process should beat its defensive benchmark broadly across folds rather than rely on isolated episodes.

## Predeclared design

- one joint candidate;
- persisted net rolling OOS returns from OKX spot BTC-USDT and ETH-USDT `1Dutc`;
- repository one-bar execution delay and 10-bps turnover cost retained;
- 26 complete, non-overlapping 90-session folds per market;
- one trailing 45-session incomplete fold excluded before testing;
- fold delta equals compounded net strategy return minus compounded net volatility-targeted-long return;
- fold success means the delta is strictly positive;
- non-circular moving-block bootstrap over consecutive complete-fold deltas;
- block length of three folds, 2,000 resamples, and 95% confidence;
- fixed seeds `2026072310` for BTC and `2026072311` for ETH;
- pass only when both lower confidence bounds exceed 0.5.

Canonical signature:

`benchmark-relative-fold-breadth-v1|markets=BTC-USDT,ETH-USDT|source=persisted-net-rolling-oos-returns|benchmark=volatility-targeted-long|complete-folds=26x90|trailing-incomplete-fold=excluded|fold-metric=compounded-strategy-return-minus-compounded-benchmark-return|success=delta>0|claim=outperformance-share>0.5-in-both-markets|resampling=noncircular-moving-block-bootstrap-over-consecutive-complete-folds|block-length=3-folds|resamples=2000|confidence=0.95|seeds=BTC-USDT:2026072310,ETH-USDT:2026072311|candidate_count=1`

No alternative benchmark, fold length, partial-fold treatment, success threshold, block length, resample count, seed, market subset, fee, execution delay, or acceptance rule was selected after observing the result.

## Results

| Market | Outperforming folds | Share | Median fold delta | Mean fold delta | 95% interval | P(share > 50%) |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 12 / 26 | 46.1538% | -1.6288% | -6.9018% | 30.7692% to 65.3846% | 26.35% |
| ETH-USDT | 9 / 26 | 34.6154% | -7.3474% | -10.8722% | 15.3846% to 53.8462% | 2.55% |

## Verdict

**Rejected.** Neither market beat volatility-targeted long in a majority of complete folds at the point estimate, and both 95% lower confidence bounds were well below 50%. One candidate was searched, zero passed, and one was rejected.

This is a benchmark-relative breadth diagnostic, not a new trading rule. It does not modify signals, parameters, costs, execution timing, folds, or holdout boundaries. No alpha or deployable improvement is claimed.

## Provenance

- provider: OKX spot;
- timeframe: `1Dutc`;
- source observations: 2,385 per market from 2020-01-11 through 2026-07-22 UTC;
- evaluated complete-fold period: 2020-01-11 through 2026-06-07 UTC;
- trailing incomplete observations excluded: 45 per market;
- source workflow: `29967772412`;
- source artifact: `8548502306` (`quant-research-source-1473-attempt-1`);
- archive SHA-256: `79cd3100c2f41d42d4fc61c1e63e765c5ec4c6b9645457c9d24469121c88b1be`;
- source head: `b6a15182dd4a688208b1c737f97a24dd295bf34c`;
- BTC return-file SHA-256: `ebf2e4cc63e6b21a2d89420e2c2dd5b3517179baacfd12931f75fb0d99bdd2ce`;
- ETH return-file SHA-256: `bd4fbc471d506069c01b86b39f7726b1bd05752bfd64e75b7d677d2d7f473047`.

The committed test fixture is an unchanged extract of the first three complete BTC-USDT folds from this artifact and includes separate SHA-256 metadata.

## Limitations

BTC and ETH remain development markets rather than untouched holdouts. Three-fold blocks preserve complete 90-session paths and short-range ordering but introduce artificial joins and do not preserve dependence beyond three folds. The strict fold-level indicator discards the magnitude of relative wins and losses; separate aggregate active-return and payoff diagnostics cover that dimension. Spread variation, nonlinear market impact, capacity, latency, and partial fills remain unmodelled beyond persisted linear transaction costs.
