# Issue #798 training-boundary eligibility audit

```text
family          trend-boundary-occupancy-opportunity-diagnostic-1h-v1
objective       repair one preregistered feature-window eligibility mismatch
candidate count 0
diagnostic count 1
parameter grid  0
markets         BTC-USDT and ETH-USDT independently
bar             immutable public confirmed OKX SPOT 1H
fee             exactly 5 bps one way inside target sleeves
OOS accessed    no
verdict changed no
correct verdict reject_trend_boundary_occupancy_opportunity_premise
```

## Evidence defect found

Issue #798 froze the eligibility rule as:

> Only Monday anchors whose complete feature window and complete 168H target lie strictly inside training are eligible.

The terminal implementation at head `d574491e00913fe56288f25ab47357eeeebe5ec4` enforced the complete-target condition but not the complete-feature condition. It admitted the Monday 22 November 2021 anchor at index `2,904`, although its 168H feature window began at index `2,737` on 15 November 2021 01:00 UTC, before the training boundary at index `2,880`.

This audit changes one thing only:

```text
require anchor - 167 >= 2,880
```

The excluded anchor used occupancy `0`, clearance `1`, and a self-contained target sleeve with turnover `2` in each market. Its gross target was `-0.2109%` for BTC and `+3.3599%` for ETH. No OOS value was parsed or inspected.

## Immutable data and sample

| Item | BTC-USDT | ETH-USDT |
|---|---:|---:|
| Workflow artifact | `8769605568` | `8769619607` |
| CSV SHA-256 | `40c7ba3dbf64b8b31c634a79e1a2d5e2fa9d60b024c1fd62848d37ed967c13a0` | `0164a5cc1730f70ad9817980d67d6350cf71013cdb759c1a153a66890127d6f8` |
| Training | `[2,880,17,520)` | `[2,880,17,520)` |
| Prior eligible anchors | 86 | 86 |
| Correct eligible anchors | 85 | 85 |
| First corrected anchor | 29 Nov 2021 00:00 UTC | 29 Nov 2021 00:00 UTC |

The source bytes, 2,160H endpoint signal, 168H state, `0.25` boundary, daily B1 target, next-open chronology, fee model, fold definitions, year definitions, bootstrap block length, draw count, seed, and bilateral gates are unchanged.

## Corrected training evidence

These are diagnostic B1 sleeve labels, not returns from an executable candidate.

| Market | Gross mean | Net mean | Turnover | Positive/zero weeks | Gross rho | 95% CI | Adverse rho | 95% CI |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | -0.4758% | -0.5275% | 88 | 15 / 45 | +0.1652 | [-0.1720,+0.4488] | +0.2397 | [-0.0880,+0.5166] |
| ETH-USDT | -0.4168% | -0.4733% | 96 | 18 / 42 | +0.1049 | [-0.1262,+0.3313] | +0.1124 | [-0.1579,+0.3957] |

Economic slopes per one standard deviation of clearance remained directionally positive but unidentified:

```text
BTC gross       +0.4684%
BTC adverse     +0.5818%
ETH gross       +0.7337%
ETH adverse     +0.3325%
```

Common-index inference with 5,000 non-circular four-week moving blocks and seed `20260731`:

```text
median gross rho       +0.1350   95% CI [-0.1250,+0.3749]
median adverse rho     +0.1761   95% CI [-0.0920,+0.4304]
markets passing gates  0/2
```

## Breadth and state quality

| Market | Positive gross folds | Positive adverse folds | Positive gross years | Positive adverse years | Occupancy IQR | High-clearance observations |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 1/6 | 3/6 | 1/3 | 1/3 | 0.0417 | 0 |
| ETH-USDT | 2/6 | 2/6 | 2/3 | 1/3 | 0.2500 | 0 |

The lower confidence bounds remain negative bilaterally. Neither market has sufficient fold breadth. Clearance remains saturated at its maximum: median occupancy is zero and median clearance is one, leaving no observations above the median. BTC also fails the minimum state-IQR gate.

## Strategy-performance fields

Because candidate count is zero:

| Requested field | Result |
|---|---|
| Executable training return/Sharpe | Not computed |
| OOS return/Sharpe | Not computed; OOS remained unread |
| Full-sample metrics | Not computed |
| B0/B1 strategy comparison | Not applicable |
| Candidate turnover/drawdown | Not applicable |
| Candidate edge per turnover | Not applicable |

The turnover and fee values above belong only to self-contained diagnostic labels.

## Verdict and disposition

```text
reject_trend_boundary_occupancy_opportunity_premise
```

The eligibility correction changes exact point estimates and one ETH target count, but not any gate, verdict, architecture disposition, or canonical trading strategy. No executable candidate, OOS evaluation, threshold rescue, alternative normalisation, market substitution, paper authority, or live authority results.

**Remaining blocker:** the boundary-occupancy feature is zero-inflated and does not provide bilateral dependence-aware evidence about active-week opportunity magnitude or adverse excursion.

**Next strategy experiment:** preregister one training-only signed path-coherence state on the same immutable training artifacts. Conditional on the causal daily-B1 long state at the anchor, use the continuous ratio of signed 168H net log return to the sum of absolute 1H log returns, and test next-168H active-sleeve gross opportunity and adverse excursion. Use one statistic, no threshold grid, no OOS, and no executable candidate unless bilateral magnitude, uncertainty, fold/year breadth, and state-dispersion gates pass.
