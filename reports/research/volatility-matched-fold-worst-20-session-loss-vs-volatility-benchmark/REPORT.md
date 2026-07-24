# Volatility-matched worst 20-session loss versus volatility-targeted long

## Hypothesis

BTC-USDT and ETH-USDT net rolling OOS strategy returns each have a less severe
mean within-fold worst compounded 20-session return than the persisted
volatility-targeted-long benchmark after that benchmark is scaled within every
complete fold to the strategy's realised sample volatility. The joint hypothesis
passes only if both 95% complete-fold moving-block-bootstrap lower bounds for the
strategy-minus-benchmark mean delta are strictly positive.

Canonical signature:

```text
volatility-matched-fold-worst-20-session-loss-vs-volatility-benchmark-v1|markets=BTC-USDT,ETH-USDT|source=persisted-net-rolling-oos-returns|benchmark=volatility-targeted-long-scaled-within-each-complete-fold-to-strategy-sample-volatility|volatility=sample-standard-deviation-ddof1|complete-folds=26x90|trailing-short-fold=excluded|window=20-sessions|fold-metric=min-within-fold-compounded-20-session-return|delta=strategy-minus-volatility-matched-benchmark|aggregate=mean-fold-delta|claim=mean-fold-delta>0-in-both-markets|resampling=noncircular-moving-block-bootstrap-over-consecutive-complete-fold-deltas|block-length=3-folds|resamples=2000|confidence=0.95|seeds=BTC-USDT:2026072321,ETH-USDT:2026072322|candidate_count=1
```

## Economic rationale

The unscaled acute-loss experiment in PR #234 reports substantially shallower
worst 20-session losses for the adaptive long/cash strategy. That comparison is
confounded by the strategy's much lower realised volatility and exposure. This
fixed follow-up asks whether the acute-loss benefit remains after a simple,
within-fold volatility normalisation of the existing defensive benchmark.

The scale is descriptive, not a deployable leverage rule: for each complete fold,
benchmark returns are multiplied by the strategy sample standard deviation divided
by the benchmark sample standard deviation, both with `ddof=1`.

## Fixed specification

- provider: OKX public spot data;
- instruments: BTC-USDT and ETH-USDT;
- timeframe: `1Dutc`;
- source workflow: `29982033676`;
- source artifact: `8553558024` (`quant-research-source-1679-attempt-1`);
- artifact SHA-256:
  `382f20d2350ebd5cb79aafdf3c901eda4ec0f1663c33d0bae9b70a920d3c82b7`;
- 2,385 aligned OOS observations per market, 2020-01-11 through 2026-07-22 UTC;
- 26 complete 90-session folds; one trailing 45-session fold excluded;
- 71 overlapping 20-session windows evaluated inside each complete fold;
- no window crosses a fold boundary;
- volatility scale recomputed separately inside each complete fold before window
  compounding;
- the bootstrap resamples the 26 observed paired fold deltas and does not recompute
  a scale across artificial block joins;
- non-circular moving-block bootstrap over consecutive fold deltas;
- block length: three folds;
- resamples: 2,000;
- confidence: 95%;
- candidate count: one;
- unchanged one-bar delay, 10-bps turnover cost, 730/90 walk-forward structure,
  and 27-candidate strategy grid.

## Results

| Market | Strategy mean worst 20-session return | Volatility-matched benchmark | Mean delta | Positive folds | Mean scale | 95% interval | P(delta > 0) |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | -7.1081% | -6.0437% | -1.0644% | 8 / 26 | 0.4170 | -1.9167% to +0.1984% | 5.25% |
| ETH-USDT | -8.1670% | -6.4895% | -1.6774% | 6 / 26 | 0.4193 | -2.6372% to -0.6924% | 0.10% |

## Verdict: rejected

Both point estimates favour the volatility-matched benchmark. BTC-USDT's interval
crosses zero and ETH-USDT's complete interval is negative. The supported unscaled
acute-loss reduction in PR #234 does not survive this fixed within-fold volatility
normalisation.

Failure reasons:

- BTC-USDT's 95% lower bound is non-positive;
- ETH-USDT's 95% lower bound is non-positive, and its upper bound is also negative.

No alpha, timing-skill, deployability, or strategy-improvement claim is made.

## Candidate accounting

```text
searched: 1
passed:   0
rejected: 1
```

No alternative volatility estimator, scale boundary, window length, fold policy,
benchmark, block length, seed, market subset, cost, delay, or acceptance threshold
was tested after viewing the result.

## Reproduction

```bash
sha256sum /path/to/quant-research-source-1679.zip

python reports/research/volatility-matched-fold-worst-20-session-loss-vs-volatility-benchmark/analysis.py \
  --artifact-dir /path/to/quant-research-source-1679 \
  --output /tmp/volatility-matched-acute-loss.json

python -m py_compile \
  reports/research/volatility-matched-fold-worst-20-session-loss-vs-volatility-benchmark/analysis.py \
  tests/test_volatility_matched_fold_worst_20_session_loss_vs_volatility_benchmark.py

pytest -q \
  tests/test_volatility_matched_fold_worst_20_session_loss_vs_volatility_benchmark.py
```

## Limitations

BTC-USDT and ETH-USDT remain development markets. The within-fold volatility scale
uses the complete realised OOS fold and is descriptive rather than ex ante
tradable. Overlapping windows are descriptive; inference uses 26 paired fold
statistics. Three-fold blocks introduce artificial joins and omit dependence
beyond three folds. Nonlinear impact, capacity, changing spreads, latency, and
partial fills remain unmodelled beyond persisted linear costs.
