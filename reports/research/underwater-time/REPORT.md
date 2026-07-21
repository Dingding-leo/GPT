# Underwater-time diagnostic

## Hypothesis

For both BTC-USDT and ETH-USDT, the strategy spends a smaller fraction of
out-of-sample days below its own previous running equity peak than the
volatility-targeted-long benchmark. The hypothesis passes only if the 95% paired
moving-block-bootstrap lower bound for
`benchmark underwater fraction - strategy underwater fraction` is positive in
both development markets.

Canonical signature:

```text
underwater-time-v1|markets=BTC-USDT,ETH-USDT|benchmark=volatility-targeted-long|metric=underwater-fraction-reduction|definition=nav-below-prior-running-peak|block=20|resamples=2000|confidence=0.95|seeds=BTC-USDT:20260722,ETH-USDT:20260723|candidate_count=4
```

## Economic rationale

Maximum drawdown measures the deepest loss but not how often capital remains
impaired. A strategy can avoid a catastrophic drawdown while spending nearly all
of its time below a prior peak. Underwater fraction therefore tests whether the
existing risk-control evidence also translates into more frequent equity highs
and faster practical capital recovery.

## Metric screen and research status

Four related diagnostics were computed and all are reported:

1. `underwater_fraction` — primary metric because it is bounded, uses every OOS
   observation, and directly measures time below the previous peak;
2. `ulcer_index` — not primary because it remains dominated by drawdown depth,
   which prior work already tested;
3. `mean_drawdown_depth` — not primary for the same overlap reason;
4. `maximum_underwater_duration` — not primary because the longest-run statistic
   is discontinuous and unstable when moving blocks are concatenated.

Because this four-metric screen used BTC-USDT and ETH-USDT development data, the
result is exploratory rather than untouched confirmatory evidence. No strategy,
candidate, fee, execution-delay, split, or sealed-market setting was changed.

## Fixed data and resampling specification

- provider: OKX public spot market data;
- instruments: BTC-USDT and ETH-USDT;
- bar: `1Dutc`;
- source workflow run: `29860303180`;
- source artifact: `8507019983` (`quant-research-246`);
- artifact SHA-256:
  `a3915a12b355c7eaed58c83c459c1d4e74f42c23815963cdab75d88fad17205a`;
- tested workflow commit: `196d925f9b3dedd3e6a6382304405952eb16a073`;
- observations: 2,340 OOS daily returns per market, 2020-01-11 through
  2026-06-07 UTC;
- paired moving-block resamples: 2,000 per market and metric;
- block length: 20 days;
- confidence: 95%;
- base seeds: 20260722 for BTC and 20260723 for ETH;
- benchmark: volatility-targeted long;
- candidates searched: four diagnostics listed above.

Return-file SHA-256 values:

- BTC-USDT:
  `539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73`;
- ETH-USDT:
  `027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6`.

## Primary result

| Market | Strategy underwater fraction | Benchmark underwater fraction | Reduction | 95% interval | P(reduction > 0) |
|---|---:|---:|---:|---:|---:|
| BTC-USDT | 97.4359% | 95.3846% | -2.0513 pp | [-4.4017, +4.9573] pp | 43.20% |
| ETH-USDT | 95.9402% | 94.7863% | -1.1538 pp | [-5.5556, +3.8034] pp | 29.25% |

## Verdict: rejected

Neither market has a positive lower confidence bound. Point estimates also run
opposite to the hypothesis: the strategy spends slightly **more** time below its
prior peak than the volatility-targeted-long benchmark in both markets.

The defensive effect therefore appears to concern drawdown **depth**, not more
frequent recovery to new highs. This does not weaken the already recorded lower-
drawdown evidence, but it blocks the stronger claim that the strategy improves
both loss depth and time under water.

## Screened diagnostics

- BTC-USDT ulcer-index reduction: `+0.213917`, 95% interval
  `[+0.010624, +0.411715]`.
- ETH-USDT ulcer-index reduction: `+0.174485`, 95% interval
  `[-0.071918, +0.336332]`.
- BTC-USDT mean-drawdown-depth reduction: `+0.157390`, 95% interval
  `[+0.000316, +0.393900]`.
- ETH-USDT mean-drawdown-depth reduction: `+0.132682`, 95% interval
  `[-0.071872, +0.327804]`.
- Maximum-underwater-duration intervals are extremely wide in both markets,
  confirming that this discontinuous statistic is not reliable under the fixed
  block-concatenation diagnostic.

## Reproduction

```bash
python reports/research/underwater-time/analysis.py \
  --artifact-dir /path/to/quant-research-246/okx \
  --output /tmp/underwater-time.json

cmp /tmp/underwater-time.json \
  reports/research/underwater-time/result.json
```

## Limitations

Underwater statistics are path dependent, and moving-block resampling creates
new paths at block boundaries. BTC-USDT and ETH-USDT are development markets.
This report does not establish alpha, improve the rejected LTC-USDT sealed-market
result, or justify leverage, live trading, or same-market retuning.
