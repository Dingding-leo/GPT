# Trend-boundary occupancy opportunity premise rejected

```text
family          trend-boundary-occupancy-opportunity-diagnostic-1h-v1
classification  training-only architecture-eligibility diagnostic
candidate count 0
diagnostic count 1
parameter grid  0
markets         BTC-USDT and ETH-USDT independently
bar             public confirmed OKX SPOT 1H
fee             exactly 5 bps one way inside each self-contained B1 sleeve
OOS accessed    no
markets passing 0/2
verdict         reject_trend_boundary_occupancy_opportunity_premise
```

## Strategy-facing change

No executable candidate was authorised. The run tested whether a fixed own-history state contains enough information to support a later causal sizing rule.

At every completed Monday `00:00 UTC` anchor, each of the latest 168 completed hours was classified by the fixed distance of the 2,160H endpoint trend from its sign boundary:

```text
endpoint_margin_t = abs(log(close_t / close_(t-2160H)))
rv168_t           = RMS of the latest 168 completed hourly log returns
scaled_distance_t = endpoint_margin_t / (sqrt(2160) * rv168_t)
near_boundary_t   = 1[scaled_distance_t <= 0.25]
occupancy         = mean(near_boundary over 168H)
clearance         = 1 - occupancy
```

The next 168H target was a self-contained daily-B1 sleeve. B1 updated only at completed `00:00 UTC` bars, used `close_t > close_(t-2160H)`, executed at the next hourly open, started from cash and liquidated to cash at the target end. The targets were gross arithmetic opportunity, exact fee-adjusted payoff and minimum within-week cumulative gross return.

## Immutable data and sample

| Item | BTC-USDT | ETH-USDT |
|---|---:|---:|
| Workflow artifact | `8769605568` | `8769619607` |
| Full CSV SHA-256 | `40c7ba3dbf64b8b31c634a79e1a2d5e2fa9d60b024c1fd62848d37ed967c13a0` | `0164a5cc1730f70ad9817980d67d6350cf71013cdb759c1a153a66890127d6f8` |
| Parsed rows | 17,520 | 17,520 |
| Eligible Monday anchors | 85 | 85 |
| First anchor | 29 Nov 2021 | 29 Nov 2021 |
| Last anchor | 10 Jul 2023 | 10 Jul 2023 |

The complete artifact bytes were hash-verified. Only rows before index `17,520` were parsed; OOS values were neither parsed nor inspected. The training interval was `[2,880,17,520)`. All 85 feature windows and all 85 subsequent 168H targets lay completely inside training.

## Training target economics

These are diagnostic B1-sleeve labels, not returns from a new strategy.

| Market | Mean gross | Mean net | Mean adverse excursion | Positive gross weeks | Inactive weeks | Turnover | Embedded fees |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | -0.4758% | -0.5275% | -2.3714% | 15/85 | 45/85 | 88 | 4.40% |
| ETH-USDT | -0.4168% | -0.4733% | -2.8078% | 18/85 | 42/85 | 96 | 4.80% |

`Full`, executable `train`, and `OOS` strategy return, Sharpe, maximum drawdown and benchmark-relative metrics were not computed because candidate count was zero. OOS remained inaccessible. The observed turnover and fees belong only to the self-contained target labels.

## Point estimates and uncertainty

| Market | Gross Spearman | 95% CI | Adverse Spearman | 95% CI | Gross slope / clearance SD | Adverse slope / clearance SD |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | +0.1652 | [-0.1720, +0.4488] | +0.2397 | [-0.0880, +0.5166] | +0.4684% | +0.5818% |
| ETH-USDT | +0.1049 | [-0.1262, +0.3313] | +0.1124 | [-0.1579, +0.3957] | +0.7337% | +0.3325% |

Slope 95% intervals also crossed zero:

```text
BTC gross      [-0.7620%, +1.6479%]
BTC adverse    [-0.4710%, +1.5820%]
ETH gross      [-0.2348%, +1.7021%]
ETH adverse    [-0.5020%, +1.3003%]
```

Common-index, four-week moving-block inference using 5,000 resamples and seed `20260731` was directionally positive but not identified:

```text
median gross rho       +0.1350   95% CI [-0.1250, +0.3749]
median adverse rho     +0.1761   95% CI [-0.0920, +0.4304]
median gross slope     +0.6010%  95% CI [-0.3642%, +1.5447%]
median adverse slope   +0.4572%  95% CI [-0.3064%, +1.2736%]
```

## Temporal breadth

| Market | Positive gross folds | Positive adverse folds | Positive gross years | Positive adverse years |
|---|---:|---:|---:|---:|
| BTC-USDT | 1/6 | 3/6 | 1/3 | 1/3 |
| ETH-USDT | 3/6 | 2/6 | 2/3 | 1/3 |

Neither market met the frozen `4/6` fold requirement for either target. Only ETH gross opportunity met the `2/3` year count; all other year-breadth gates failed.

## Failure mechanism

The fixed state was saturated at maximum clearance:

| Market | Occupancy Q1 | Median | Q3 | IQR | Zero-occupancy weeks | Strictly above median clearance |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 0.0000 | 0.0000 | 0.0417 | 0.0417 | 61/85 | 0 |
| ETH-USDT | 0.0000 | 0.0000 | 0.2500 | 0.2500 | 49/85 | 0 |

Clearance therefore had median `1.0`, its mathematical maximum. There were no observations strictly above the median in either market, so the preregistered requirement for at least 20 observations on each side of the median and the high-versus-low comparison failed closed. BTC additionally failed the minimum occupancy-IQR gate.

The slight positive full-sample associations were partly coupled to inactive target weeks. BTC had 45 zero-exposure weeks and ETH had 42. Among active weeks only, gross Spearman fell to `+0.1420` for BTC and `+0.0689` for ETH; adverse-excursion Spearman fell to `+0.0358` for BTC and became `-0.1250` for ETH. The absolute boundary-distance state therefore did not robustly distinguish an economically useful trend opportunity from a cash/inactive week.

## Correctness repair and verification

Before evidence was frozen, the median-balance implementation was repaired to follow the literal preregistered rule: low clearance is strictly below the training median, high clearance is strictly above it, and ties are reported separately. Treating median ties as a high state would have hidden the state saturation. This repair did not alter source data, feature values, target labels, point correlations, moving-block draws, slopes, fold/year results or the rejection verdict.

The standalone reproducer uses only the repository's NumPy/Pandas dependency boundary. Two complete replays were byte-identical:

```text
reproducer SHA-256  da316b31dd3f4b4070c159b70a6e4735b16c84e101177b2edb8160a3ea9285c6
evidence SHA-256    3f515324e23c5e7c7b4d0ef69f1caac5d04f2e22038200e5e47fafcabd435a04
```

A separate vectorised reconstruction independently matched both markets' anchor count, target inactivity counts and both Spearman point estimates.

## Verdict

```text
reject_trend_boundary_occupancy_opportunity_premise
```

The premise failed dependence-aware uncertainty, fold breadth, adverse-excursion year breadth and median-state balance bilaterally; BTC also failed state dispersion. No executable sizing candidate, OOS evaluation, threshold rescue, smoothing, alternate normalisation, alternate volatility window, alternate trend horizon or improvised market cohort is authorised.

**Remaining blocker:** a useful own-history state must retain broad continuous variation and forecast active-week payoff magnitude or adverse-tail behaviour, rather than mostly identifying that the endpoint trend never approached a narrowly normalised absolute boundary.

**Next strategy experiment:** preregister one training-only **signed path-coherence state** on the same immutable training artifacts. Use one fixed continuous statistic—the signed 168H net log return divided by the sum of absolute 1H log returns—to test whether orderly positive path efficiency, conditional on the causal daily-B1 long state, predicts the next 168H active-sleeve gross opportunity and adverse excursion. Use no threshold grid, no boundary-distance transform, no OOS and no executable candidate unless bilateral magnitude and breadth gates pass.
