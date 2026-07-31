# Trend-boundary occupancy opportunity premise rejected

```text
Family          trend-boundary-occupancy-opportunity-diagnostic-1h-v1
Classification  Training-only architecture-eligibility diagnostic
Candidate count 0
Diagnostic count 1
Parameter grid  0
Markets         BTC-USDT and ETH-USDT independently
Bar             Public confirmed OKX SPOT 1H
Fee             Exactly 5 bps one way inside each target sleeve
Issue           #798
OOS accessed    False
Markets passing 0/2
Verdict         reject_trend_boundary_occupancy_opportunity_premise
```

## Strategy-facing objective

The experiment tested whether distance from the daily 2,160H endpoint-trend boundary identifies weeks in which the frozen B1 long/cash policy has more gross opportunity and less adverse excursion. It was deliberately diagnostic-only: no position-sizing, veto, or entry candidate was authorised.

At each completed Monday `00:00 UTC` anchor, every completed hour in the preceding 168H was classified using:

```text
endpoint_margin_t = abs(log(close_t / close_(t-2160H)))
rv168_t           = RMS of the latest 168 completed hourly log returns
scaled_distance_t = endpoint_margin_t / (sqrt(2160) * rv168_t)
near_boundary_t   = 1[scaled_distance_t <= 0.25]
occupancy         = mean(near_boundary over the latest 168H)
clearance         = 1 - occupancy
```

The fixed `0.25` boundary and every inference gate were frozen in issue #798 before target-performance computation.

The next-week target was a self-contained 168H daily-B1 sleeve:

```text
B1_t = 1[close_t > close_(t-2160H)] at completed 00:00 UTC decisions
```

Each sleeve began from cash, executed at the next hourly open, carried the daily state intraday, and liquidated to cash at the window end. Embedded fees were `0.0005 × abs(position change)`, including initial entry and terminal liquidation.

## Immutable data and sample

| Item | Frozen contract |
|---|---|
| BTC artifact | `8769605568` |
| BTC CSV SHA-256 | `40c7ba3dbf64b8b31c634a79e1a2d5e2fa9d60b024c1fd62848d37ed967c13a0` |
| ETH artifact | `8769619607` |
| ETH CSV SHA-256 | `0164a5cc1730f70ad9817980d67d6350cf71013cdb759c1a153a66890127d6f8` |
| Frozen prefix | First 43,441 contiguous confirmed 1H rows |
| Frozen span | 24 July 2021–8 July 2026 UTC |
| Training used | `[2,880,17,520)` |
| Development OOS | `[17,520,43,440)` — unread |
| Eligible anchors | 86 completed Monday anchors per market |
| Breadth | Six contiguous 2,160H training folds and three calendar years |
| Uncertainty | 5,000 common-index non-circular four-week moving blocks |
| Seed | `20260731` |

No cross-sectional operation, market pooling, pair/spread construction, shorting, leverage, credentials, private endpoints, accounts, orders, enabled adapters, synthetic data, or 15-minute data was used.

## Results

| Market | Occupancy Q25 / Q50 / Q75 | Mean gross opportunity | Mean net sleeve payoff | Gross rho [95% CI] | Adverse-excursion rho [95% CI] | Embedded turnover |
|---|---:|---:|---:|---:|---:|---:|
| BTC | 0.000 / 0.000 / 0.0387 | -0.4727% | -0.5250% | +0.161 [-0.158, +0.450] | +0.226 [-0.081, +0.513] | 90 |
| ETH | 0.000 / 0.000 / 0.2307 | -0.3729% | -0.4299% | +0.114 [-0.116, +0.332] | +0.102 [-0.150, +0.385] | 98 |

The standardized economic slopes were directionally positive:

| Market | Gross opportunity per 1 SD clearance | Adverse excursion per 1 SD clearance |
|---|---:|---:|
| BTC | +0.4664 percentage points | +0.5487 percentage points |
| ETH | +0.7534 percentage points | +0.3114 percentage points |

However, none of the dependence-aware lower bounds was positive.

Common-index inference:

```text
Median gross-opportunity rho       +0.1378
95% interval                       [-0.1206, +0.3813]

Median adverse-excursion rho       +0.1636
95% interval                       [-0.0846, +0.4222]

Markets passing every frozen gate  0/2
```

## Temporal breadth

| Market | Positive gross folds | Positive gross years | Positive adverse-excursion folds | Positive adverse-excursion years |
|---|---:|---:|---:|---:|
| BTC | 1/6 | 1/3 | 3/6 | 1/3 |
| ETH | 2/6 | 2/3 | 2/6 | 1/3 |

Two folds in each market had no clearance variation and therefore no defined slope. The remaining signs were inconsistent across time.

## Failure mechanism

The exact state was strongly zero-inflated. Median occupancy was zero in both markets, so median clearance was `1.0`; all 86 observations fell on the preregistered low side and none on the high side. BTC also failed the minimum occupancy-IQR requirement (`0.0387 < 0.10`). Thus the state could not support the intended ordered exposure groups.

A descriptive, non-authorising audit compared weeks with no near-boundary hour against weeks with at least one such hour:

| Market | No-boundary / boundary weeks | Gross mean delta | Adverse-excursion mean delta | Turnover mean delta |
|---|---:|---:|---:|---:|
| BTC | 62 / 24 | +1.2423 pp | +1.3127 pp | -0.976 |
| ETH | 50 / 36 | +0.2311 pp | +0.6491 pp | -0.524 |

This ordering is economically suggestive, but it is not sufficient evidence. The binary split was not the preregistered statistic, the association lacked temporal breadth, and both moving-block intervals crossed zero. Converting this observation into an executable veto would be post-result threshold rescue.

The diagnostic also contained many inactive target sleeves: BTC had 45 zero-gross weeks and ETH had 42. Consequently, part of the apparent clearance relationship reflects persistence of B1 cash states rather than richer conditional long opportunity.

## Required strategy-performance fields

Candidate count was zero, so no executable strategy was evaluated.

| Requested field | Result |
|---|---|
| Training strategy return / Sharpe | Not computed — diagnostic only |
| Development-OOS return / Sharpe | Not computed; OOS remained unread |
| Full-sample strategy metrics | Not computed |
| B0/B1 benchmark comparison | Not applicable to a non-executable diagnostic |
| Strategy turnover and fees | Not applicable |
| Strategy maximum drawdown | Not applicable |
| Strategy edge per turnover | Not applicable |
| Fold/year strategy profitability | Not applicable; reported breadth concerns diagnostic slopes |
| Candidate acceptance | No candidate authorised |

The turnover and fee totals above belong only to the self-contained weekly B1 target labels; they are not candidate trading results.

## Reproducibility

Two independent executions of the deterministic reproducer were byte-identical.

```text
Reproducer SHA-256  88378b63d4842e95d13f48872a11615acc426797a743d3d18605160845023fa6
Evidence SHA-256    9f119b4b87eb291ec4412451791857ad525335b22f81c5fc9ae74656c6250394
Summary SHA-256     698b52dba59ed4a99ae7fae9f28a1b29351a88ad376d78da8d7e09893dc00c6b
```

## Verdict

```text
reject_trend_boundary_occupancy_opportunity_premise
```

No executable boundary-occupancy candidate, OOS evaluation, smoothing, threshold change, alternative volatility normalisation, market substitution, or binary-presence rescue is authorised.

**Remaining blocker:** the distance-threshold state has weak directional economics but is too sparse and temporally unstable to distinguish a durable B1 opportunity from an inactive or boundary-churning week.

**Next strategy experiment:** preregister one training-only **daily-B1 fragmentation state** on the same immutable training artifacts. Use the exact count of completed daily B1 sign transitions during the preceding 168H—without a distance threshold—as the sole predictor of next-week gross B1 opportunity and adverse excursion. Test whether lower fragmentation has bilateral magnitude, temporal-breadth, and moving-block evidence before authorising any fresh-cohort executable rule.
