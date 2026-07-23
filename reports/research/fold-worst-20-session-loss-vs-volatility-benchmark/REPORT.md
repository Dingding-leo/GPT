# Worst 20-session loss versus volatility-targeted long

## Hypothesis

BTC-USDT and ETH-USDT net rolling OOS strategy returns each have a less severe
mean within-fold worst compounded 20-session return than the persisted
volatility-targeted-long benchmark. The joint hypothesis passes only if both 95%
complete-fold moving-block-bootstrap lower bounds for the strategy-minus-benchmark
mean delta are strictly positive.

Canonical signature:

```text
fold-worst-20-session-loss-vs-volatility-benchmark-v1|markets=BTC-USDT,ETH-USDT|source=persisted-net-rolling-oos-returns|benchmark=volatility-targeted-long|complete-folds=26x90|trailing-short-fold=excluded|window=20-sessions|fold-metric=min-within-fold-compounded-20-session-return|delta=strategy-minus-benchmark|aggregate=mean-fold-delta|claim=mean-fold-delta>0-in-both-markets|resampling=noncircular-moving-block-bootstrap-over-consecutive-complete-fold-deltas|block-length=3-folds|resamples=2000|confidence=0.95|seeds=BTC-USDT:2026072315,ETH-USDT:2026072316|candidate_count=1
```

## Economic rationale

Maximum drawdown uses a variable and potentially long peak-to-trough interval,
while daily expected shortfall measures isolated sessions. A defensive long/cash
process should also reduce acute losses over an approximately one-month holding
horizon. This experiment therefore evaluates the worst compounded 20-session
return inside each actual 90-session OOS deployment fold.

## Fixed specification

- provider: OKX public spot market data;
- instruments: BTC-USDT and ETH-USDT;
- timeframe: `1Dutc`;
- source workflow: `29982033676`;
- source artifact: `8553558024` (`quant-research-source-1679-attempt-1`);
- artifact SHA-256:
  `382f20d2350ebd5cb79aafdf3c901eda4ec0f1663c33d0bae9b70a920d3c82b7`;
- source code head: `c3bd405ac7ddd6a7fd6d8eff8d9372a05a8855b4`;
- current main merge commit: `2cb492b66873bccbf5535c8f3721feb3ee52c880`;
- 2,385 OOS observations per market from 2020-01-11 through 2026-07-22 UTC;
- 26 complete 90-session folds; one trailing 45-session fold excluded;
- 71 overlapping 20-session windows evaluated inside each complete fold;
- no window crosses a fold boundary;
- non-circular moving-block bootstrap over consecutive fold deltas;
- block length: three folds;
- resamples: 2,000;
- confidence: 95%;
- candidate count: one;
- unchanged one-bar execution delay, 10-bps turnover cost, 730/90 walk-forward
  structure, and 27-candidate selection grid.

Return-file SHA-256 values:

- BTC-USDT:
  `ebf2e4cc63e6b21a2d89420e2c2dd5b3517179baacfd12931f75fb0d99bdd2ce`;
- ETH-USDT:
  `bd4fbc471d506069c01b86b39f7726b1bd05752bfd64e75b7d677d2d7f473047`.

## Result

| Market | Strategy mean fold worst 20-session return | Benchmark | Reduction | Positive folds | 95% interval | P(mean reduction > 0) |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | -7.1081% | -17.1662% | +10.0580% | 24 / 26 | +5.6151% to +13.5918% | 100.00% |
| ETH-USDT | -8.1670% | -16.9726% | +8.8056% | 22 / 26 | +4.7398% to +11.7485% | 100.00% |

## Verdict: supported, narrowly scoped

Both lower confidence bounds are positive. Under this single predeclared design,
the strategy had materially less severe acute 20-session losses than the
volatility-targeted-long benchmark across the complete BTC-USDT and ETH-USDT OOS
folds.

This is a risk-control result, not an alpha claim. It does not show higher total
return, superior Sharpe or Calmar, untouched-holdout validity, or deployability.
The strategy also has materially lower average exposure than the benchmark, so
this diagnostic does not isolate timing skill from exposure reduction.

## Candidate accounting

```text
searched: 1
passed:   1
rejected: 0
```

No alternative window length, fold definition, benchmark, block length, seed,
confidence level, market subset, cost, delay, or acceptance threshold was tested
after viewing the result.

## Reproduction

```bash
sha256sum /path/to/quant-research-source-1679.zip

python reports/research/fold-worst-20-session-loss-vs-volatility-benchmark/analysis.py \
  --artifact-dir /path/to/quant-research-source-1679 \
  --output /tmp/fold-worst-20-session-loss.json

python - <<'PY'
import json
from pathlib import Path

recomputed = json.loads(Path("/tmp/fold-worst-20-session-loss.json").read_text())
committed = json.loads(
    Path(
        "reports/research/fold-worst-20-session-loss-vs-volatility-benchmark/result.json"
    ).read_text()
)
assert recomputed == committed
PY

python -m py_compile \
  reports/research/fold-worst-20-session-loss-vs-volatility-benchmark/analysis.py \
  tests/test_fold_worst_20_session_loss_vs_volatility_benchmark_report.py

pytest -q \
  tests/test_fold_worst_20_session_loss_vs_volatility_benchmark_report.py
```

## Limitations

BTC-USDT and ETH-USDT are development markets, not untouched holdouts. Overlapping
20-session windows within a fold are descriptive; uncertainty is estimated from
26 paired fold-level statistics rather than treating the 1,846 windows as
independent. Three-fold blocks preserve short-range fold order but introduce
artificial joins and do not preserve dependence beyond three folds. The result is
not volatility matched and does not model nonlinear market impact, capacity,
changing spread, latency, or partial fills beyond persisted linear costs.
