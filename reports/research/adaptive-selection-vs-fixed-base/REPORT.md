# Adaptive Rolling Selection Versus the Fixed Base Configuration

## Hypothesis

The repository's adaptive 730-bar selection / 90-bar test process improves both annualized
arithmetic mean net return and annualized Sharpe versus the repository's fixed base
configuration in BTC-USDT and ETH-USDT.

Economic rationale: the 27-candidate rolling search adds complexity and selection risk. It
should not be retained as performance-enhancing machinery unless it demonstrates a reliable
incremental benefit over the ex ante base configuration already declared in
`config/okx_research.json`: momentum 90, reversal 5, trend weight 0.70, 30-day volatility,
50% target volatility, long/cash positions, one-bar execution delay, and 10 bps per unit
turnover.

## Predeclared method

- Markets: OKX spot BTC-USDT and ETH-USDT `1Dutc`, development evidence only.
- Evaluation window: 2,340 observations from 2020-01-11 through 2026-06-07 UTC.
- Adaptive path: the persisted net rolling OOS path from 26 non-overlapping 90-bar folds,
  with each fold selected using only its preceding 730 bars and the full 27-candidate grid.
- Fixed comparator: one uninterrupted path using the repository base configuration. The
  comparator is not reset at fold boundaries and carries its position continuously.
- Both paths use the same prices, one-bar execution delay, long/cash constraint, volatility
  target, and 10 bps turnover cost.
- Before comparison, the script reconstructs the adaptive path from the immutable snapshot
  and selected fold parameters. Maximum absolute return error is below `1e-15` in both
  markets.
- Uncertainty: 2,000 paired non-circular moving-block resamples with 20-session blocks and
  market-specific deterministic seeds.
- Metrics: adaptive-minus-fixed annualized arithmetic mean and annualized Sharpe.
- Pass rule: both 95% lower bounds must be strictly positive in both markets.

Exactly one joint hypothesis was tested. No alternate fixed candidate, metric, block length,
seed, market subset, cost, delay, or acceptance threshold was selected after viewing the
results.

## Results

| Market | Adaptive mean | Fixed mean | Mean delta (95% interval) | Adaptive Sharpe | Fixed Sharpe | Sharpe delta (95% interval) |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 17.168957% | 13.594679% | +3.574277% [-8.827333%, +14.820544%] | 0.725970 | 0.551741 | +0.174229 [-0.343948, +0.598542] |
| ETH-USDT | 13.704095% | 15.934722% | -2.230627% [-17.868573%, +13.023728%] | 0.537986 | 0.618610 | -0.080624 [-0.679730, +0.455711] |

BTC point estimates favor adaptive selection, but neither confidence interval excludes zero.
ETH point estimates favor the fixed base configuration, and both intervals also cross zero.
The joint hypothesis is therefore **rejected**. The evidence does not establish that rolling
parameter selection adds net mean-return or Sharpe value over the fixed base configuration.
This is not a recommendation to replace the adaptive process; it is evidence that its
incremental performance benefit is unproven on these development markets.

## Candidate accounting

- Joint hypotheses searched: 1.
- Supported: 0.
- Rejected: 1.
- Fixed comparators searched: 1, the pre-existing repository base configuration.

Canonical signature:

`adaptive-selection-vs-fixed-base-v1|markets=BTC-USDT,ETH-USDT|source=immutable-OKX-1Dutc-snapshots-and-persisted-net-rolling-oos-returns|adaptive=repository-730-selection-90-test-27-grid|fixed-base=momentum90-reversal5-trend0.70-vol30-targetvol0.50-long-cash|execution=one-bar-delay-10bps-continuous-position|evaluation=2020-01-11..2026-06-07-2340-bars|metrics=annualized-arithmetic-mean-delta,annualized-sharpe-delta|resampling=paired-noncircular-moving-block-bootstrap-20|resamples=2000|confidence=0.95|pass=both-metric-lower-bounds-positive-in-both-markets|candidate_count=1`

## Provenance

- Source workflow: `29918619194`.
- Source artifact: `8528966554`, `quant-research-source-973-attempt-1`.
- Artifact SHA-256:
  `67bbf4136107a98bde8ddb118c6449d9db4da75b7eb7e9d3da82f822b156f43b`.
- Source head: `007935d8581a6c1b622ce0a7702faaa0884cf227`.
- Source base: `762151882255be7b2e3bd26370151b8182526fd3`.
- Exact snapshot, report, and persisted-return hashes are recorded in `result.json`.

## Reproduction

```bash
python reports/research/adaptive-selection-vs-fixed-base/analysis.py \
  --artifact-dir /path/to/unpacked/quant-research-source-973-attempt-1 \
  --output /tmp/recomputed-adaptive-vs-fixed.json

cmp -s \
  /tmp/recomputed-adaptive-vs-fixed.json \
  reports/research/adaptive-selection-vs-fixed-base/result.json
```

## Limitations

BTC and ETH are development markets, not untouched holdouts. Moving-block concatenation
creates artificial joins while only resampling observed paired returns. The fixed comparator
is the existing base configuration, not an exhaustively selected best fixed candidate.
Spread, market impact, liquidity, capacity, latency, and partial fills remain unmodeled.
