# Selection-margin predictiveness

## Hypothesis

For both BTC-USDT and ETH-USDT, the gap between the selected candidate's in-sample selection
score and the runner-up score has a positive Spearman rank correlation with the immediately
subsequent out-of-sample fold total return. The joint hypothesis passes only if both 95% paired
moving-block-bootstrap lower bounds are above zero.

Canonical signature:

```text
selection-margin-predictiveness-v1|markets=BTC-USDT,ETH-USDT|predictor=runner-up-selection-score-gap|outcome=subsequent-test-fold-total-return|metric=spearman-rank-correlation|resampling=paired-noncircular-moving-block-over-folds|block=9|block-rationale=ceil(730-selection-bars/90-test-bars)|resamples=2000|confidence=0.95|seeds=BTC-USDT:20260722,ETH-USDT:20260723|candidate_count=1
```

## Economic rationale

A wider selection-score margin should indicate a more clearly distinguished candidate if the
selection objective contains useful information about future performance. A positive relationship
with the next test fold would support interpreting the margin as a confidence diagnostic. A weak or
negative relationship would show that a decisive in-sample winner does not reliably imply a better
subsequent OOS result.

The predictor is computed only from each fold's 730-bar selection window. The outcome is the total
return of the following non-overlapping 90-bar test window, so the test introduces no future
information into candidate selection.

## Fixed specification and candidate accounting

Exactly one specification was tested:

- predictor: persisted `runner_up_score_gap` from each selection window;
- outcome: persisted total return from the immediately subsequent test fold;
- metric: Spearman rank correlation across the 26 ordered folds;
- resampling: paired non-circular moving blocks over fold pairs;
- block length: 9 folds, equal to `ceil(730 / 90)`, to preserve dependence caused by overlapping
  selection windows;
- resamples: 2,000;
- confidence: 95%;
- deterministic seeds: 20260722 for BTC-USDT and 20260723 for ETH-USDT.

No alternative predictor, outcome metric, transformation, block length, confidence level, seed,
market subset, parameter family, fee, fold, or threshold was searched after observing the result.

## Results

| Market | Folds | Point Spearman | 95% interval | P(correlation > 0) |
|---|---:|---:|---:|---:|
| BTC-USDT | 26 | -0.241709 | [-0.783598, +0.000483] | 2.60% |
| ETH-USDT | 26 | +0.303932 | [-0.224312, +0.753778] | 79.25% |

BTC-USDT has a negative point relationship and only 2.60% of block-bootstrap samples are positive.
ETH-USDT has a positive point relationship, but its lower confidence bound remains negative.

## Verdict: rejected

Neither market has a positive 95% lower bound, and BTC-USDT's point estimate is negative. The
evidence does not support using the selection-score margin as a reliable predictor of subsequent OOS
fold performance. No alpha, parameter-selection improvement, or deployable confidence rule is
claimed.

## Data and provenance

- provider: OKX public spot data;
- instruments: BTC-USDT and ETH-USDT development markets;
- timeframe: `1Dutc`;
- source workflow run: `29883888690`;
- source artifact: `8515812291` (`quant-research-429`);
- artifact SHA-256: `9d3cfe6e86ad93dc6ed068d2a69029a099abf7a07b05de6b9abfa79c7e7710e6`;
- tested merge commit: `7ce09c5b1b42e6e4ed5ceea113960b6fa5132fbd`;
- persistent source head: `4d8cfb358e2799290f7fa048c6c04177e63676f7`;
- source base: `e51ac7733597484fdc6e27c39e6eb534b7a11fd5`;
- BTC-USDT walk-forward report SHA-256:
  `8c68767eeba6d6ecdc3716f194dc9cf3d48cb0a51fea49f6a4e10f771c03914b`;
- ETH-USDT walk-forward report SHA-256:
  `792de43822f91b9475885f511d23fd68e002473b8fcc67ec8eb4a867e320ac99`;
- 26 folds per market, each testing 27 candidates on the preceding selection window;
- one-bar execution delay, 10 bps transaction cost, 730-bar selection windows, and 90-bar test
  windows remain unchanged from the source workflow.

The persisted JSON contains ordered arrays of every fold ID, score gap, and subsequent test return so
the point statistic can be independently recomputed. The analysis validates the source report's
explicit UTC selection/test chronology and contiguous non-overlapping test folds before extracting
those pairs.

## Limitations

BTC-USDT and ETH-USDT are development evidence, not untouched holdouts. The fold count is small, and
adjacent selection windows overlap substantially. The 9-fold moving block addresses that dependence
under one predeclared convention but does not prove the absence of all selection bias. This is a
meta-research diagnostic, not a trading signal or live-execution model.
