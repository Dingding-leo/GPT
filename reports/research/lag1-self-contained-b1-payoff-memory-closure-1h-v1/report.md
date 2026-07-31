# Lag-1 self-contained B1-payoff memory closure

```text
family          lag1-self-contained-b1-payoff-memory-closure-1h-v1
issue           #795
candidate count 0
diagnostic count 1
parameter grid  0
bar             public confirmed OKX SPOT 1H
fee             exactly 5 bps one way inside each weekly sleeve
sample          training only [2880,17520)
OOS accessed    no
verdict         reject_lag1_self_contained_b1_payoff_memory_premise
```

## Strategy-facing question

The two fixed-cohort attempts to evaluate lagged weekly B1-payoff sizing stopped before performance because their public instruments were invalid or lacked the frozen history. Rather than select more symbols, this closure diagnostic asks whether one completed, fee-adjusted, self-contained 168H daily-B1 sleeve predicts the next sleeve on the already verified canonical BTC/ETH training data.

At every completed Monday 00:00 UTC anchor, the label uses decisions `q=t-169,...,t-2`, next-open hourly returns `open_(q+2)/open_(q+1)-1`, initial/internal/terminal turnover, and `0.0005 * turnover` fees. Consecutive labels are non-overlapping. Only rows before index 17,520 enter a statistic.

## Immutable data

| Market | Workflow | Artifact | Artifact archive SHA-256 | CSV SHA-256 |
|---|---:|---:|---|---|
| BTC-USDT | 30567744552 | 8769605568 | `269593ae016672396ad31ad7f11ced77a8b492a3350f7a827e2af0b3e4de7700` | `40c7ba3dbf64b8b31c634a79e1a2d5e2fa9d60b024c1fd62848d37ed967c13a0` |
| ETH-USDT | 30567744552 | 8769619607 | `935ce567d34bb5fc835f413bada976ce8a277d0383254b8c2c096f64f15d7062` | `0164a5cc1730f70ad9817980d67d6350cf71013cdb759c1a153a66890127d6f8` |

The frozen prefix contains 43,441 contiguous confirmed rows from 24 July 2021 00:00 UTC through 8 July 2026 00:00 UTC. The diagnostic uses warm-up `[0,2880)` and training `[2880,17520)` only. Development OOS `[17520,43440)` remains unread for statistics.

## Results

Each market produced 86 weekly labels and 85 consecutive lag pairs. Uncertainty uses 5,000 common-index, non-circular four-pair moving-block resamples with seed `20260731`.

| Market | Corr | Corr 95% CI | Sign delta | Sign 95% CI | Mean delta | Mean 95% CI | Positive folds | Positive years |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | -0.0684 | [-0.3630, +0.1693] | +0.3159 | [-0.0481, +0.6090] | -0.8575% | [-3.4364%, +0.7965%] | 2/6 | 1/3 |
| ETH-USDT | -0.0187 | [-0.2255, +0.1800] | +0.2396 | [+0.0441, +0.4200] | -1.0350% | [-6.2803%, +2.4699%] | 2/6 | 1/3 |

### Transition counts

| Market | Positive→positive | Positive→non-positive | Non-positive→positive | Non-positive→non-positive |
|---|---:|---:|---:|---:|
| BTC-USDT | 6 | 8 | 8 | 63 |
| ETH-USDT | 7 | 11 | 10 | 57 |

### State balance, turnover and concentration

| Market | Positive lagged states | Non-positive lagged states | Mean weekly payoff | Embedded turnover | Embedded fees | Largest absolute-payoff share |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 14 | 71 | -0.5352% | 92 | 4.60% | 11.47% |
| ETH-USDT | 18 | 67 | -0.4386% | 100 | 5.00% | 12.31% |

### Common-index inference

```text
Median lag-1 correlation   -0.0435  95% CI [-0.2639, +0.1456]
Median sign delta          +0.2778  95% CI [+0.0380, +0.4913]
Median mean delta          -0.9462% 95% CI [-4.0102%, +1.0529%]
Markets passing all gates   0/2
```

## Failure mechanism

A positive previous sleeve increased the frequency of a positive next sleeve, but not its economic payoff. BTC's next-positive rate rose from 11.27% to 42.86%, yet mean next payoff deteriorated from -0.3769% to -1.2344%. ETH's rate rose from 14.93% to 38.89%, while mean next payoff deteriorated from -0.2419% to -1.2769%.

The predictor therefore encodes a weak sign-clustering effect while failing the magnitude objective required for sizing. Positive prior sleeves were sparse—14 BTC and 18 ETH observations, below the frozen 20-state minimum—and the relationship appeared in only two of six complete folds and one of three years in each market. Both point correlations and both conditional mean deltas were negative; their dependence-aware intervals crossed zero.

This rejects the economic payoff-memory premise, not merely one sizing threshold. Extending the lag, smoothing payoff history, changing the sign threshold, substituting another market, or mapping the same label to a different fixed exposure would be same-family rescue.

## Strategy performance fields

No executable candidate was evaluated. Train/OOS/full strategy return, Sharpe, maximum drawdown, strategy turnover, edge per turnover and B0/B1 benchmark comparisons are intentionally not computed. The reported turnover and fees belong only to the causal self-contained B1 labels. No canonical strategy, paper authority or live authority changes.

## Verdict

`reject_lag1_self_contained_b1_payoff_memory_premise`

The remaining blocker is not fee accounting or cadence. A useful sizing state must forecast payoff magnitude or downside asymmetry, not merely the probability that the next weekly sleeve is above zero.

The next experiment should use the same canonical training-only discipline to test one orthogonal **trend-opportunity state**: whether the fraction of the preceding 168H spent near the 2,160H decision boundary predicts the next week's B1 gross opportunity and adverse excursion. Predeclare one boundary-distance statistic, one cadence and zero grid; reject it before a fresh-cohort strategy if bilateral magnitude evidence is absent.
