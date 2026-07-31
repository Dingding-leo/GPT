# Daily positive-trend age opportunity premise rejected

```text
family          daily-positive-trend-age-opportunity-diagnostic-1h-v1
classification  training-only architecture-eligibility diagnostic
candidate count 0
diagnostic count 1
parameter grid  0
markets         BTC-USDT and ETH-USDT independently
bar             immutable public confirmed OKX SPOT 1H
fee             exactly 5 bps one way inside self-contained target sleeves
OOS accessed    no
markets passing 0/2
verdict         reject_daily_positive_trend_age_opportunity_premise
```

## Strategy-facing change

This run replaced the sparse weekly path-coherence state with a daily state available at every positive daily 2,160H endpoint-trend decision:

```text
B1_t        = 1[close_t > close_(t-2160H)] at completed 00:00 UTC
age_days_t  = consecutive positive daily B1 decisions including t
state_t     = log1p(age_days_t)
```

The falsifiable premise was a trend-survival effect: an older uninterrupted positive endpoint trend should have better next-day carry and less adverse within-day movement than a new crossing. No threshold, fitted coefficient, rank, smoothing, market pooling or executable position rule was introduced.

Every eligible anchor created one independent 24H B1-long label from cash. It entered at the next hourly open, held one unit for 24 open-to-open returns, and liquidated at the terminal open. Gross opportunity and minimum cumulative gross return were the primary targets; net payoff charged exactly 5 bps on entry and 5 bps on liquidation.

## Immutable data and sample

| Item | BTC-USDT | ETH-USDT |
|---|---:|---:|
| Artifact | `8769605568` | `8769619607` |
| CSV SHA-256 | `40c7ba3dbf64b8b31c634a79e1a2d5e2fa9d60b024c1fd62848d37ed967c13a0` | `0164a5cc1730f70ad9817980d67d6350cf71013cdb759c1a153a66890127d6f8` |
| Parsed rows | 17,520 | 17,520 |
| Eligible daily calendar anchors | 609 | 609 |
| B1-long active anchors | 246 | 272 |
| Positive regimes beginning in scored calendar | 14 | 11 |
| First / last anchor | 21 Nov 2021 / 22 Jul 2023 | 21 Nov 2021 / 22 Jul 2023 |

Only the first 17,520 rows were parsed after full-file hash verification. Training was `[2,880,17,520)`; development OOS `[17,520,43,440)` and every later row remained unread by the diagnostic. The target contract required `anchor+25 < 17,520`, so every final terminal open remained strictly inside training.

## Target-sleeve economics

These are target labels, not returns from a proposed executable strategy.

| Market | Mean gross | Mean net | Mean adverse excursion | Positive gross days | Positive net days | Turnover | Embedded fees |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | -0.1781% | -0.2781% | -1.6394% | 112/246 | 107/246 | 492 | +24.6000% |
| ETH-USDT | -0.1368% | -0.2368% | -2.0030% | 128/272 | 126/272 | 544 | +27.2000% |

Maximum absolute gross-day concentration was 2.20% for BTC and 1.54% for ETH. Candidate count was zero, so executable strategy return, Sharpe, maximum drawdown, edge per turnover, B0/B1 strategy comparison, OOS metrics and full-sample metrics were not computed. Per-sleeve adverse excursion is reported instead of candidate drawdown.

## State support

| Market | Age min | Q1 | Median | Q3 | Max | State IQR | Low / high support |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 1d | 7.25d | 37.50d | 91.75d | 153d | 2.4210 | 123 / 123 |
| ETH-USDT | 1d | 11.75d | 36.00d | 70.00d | 131d | 1.7177 | 137 / 135 |

Unlike the preceding weekly diagnostic, the daily state passed dispersion, median-support and bootstrap-validity gates bilaterally. It therefore repaired the sample-support bottleneck.

## Point estimates and uncertainty

| Market | Gross rho | 95% CI | Adverse rho | 95% CI | Gross slope / state SD | Adverse slope / state SD |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | +0.0589 | [-0.0488,+0.1683] | +0.0649 | [-0.0490,+0.1873] | +0.2288% | +0.1321% |
| ETH-USDT | +0.0247 | [-0.0847,+0.1189] | +0.0516 | [-0.0668,+0.1718] | -0.0083% | +0.0511% |

All four per-market correlation intervals crossed zero. ETH's gross standardized slope was slightly negative despite a weakly positive rank statistic.

```text
BTC valid draws             5,000 / 5,000 = 100.00%
ETH valid draws             5,000 / 5,000 = 100.00%
common valid draws          5,000 / 5,000 = 100.00%
common median gross rho     +0.0418  95% CI [-0.0498,+0.1292]
common median adverse rho   +0.0583  95% CI [-0.0430,+0.1645]
common median gross slope   +0.1102% 95% CI [-0.1773%,+0.4256%]
common median adverse slope +0.0916% 95% CI [-0.1031%,+0.3433%]
```

The 5,000 common-calendar non-circular seven-day moving-block draws were all valid, but every individual and common lower bound remained below zero.

## Median ordering

| Market | High-minus-low gross | High-minus-low adverse | High-minus-low net |
|---|---:|---:|---:|
| BTC-USDT | +0.3345% | +0.0450% | +0.3345% |
| ETH-USDT | +0.3383% | +0.2018% | +0.3383% |

The older half had better unconditional mean economics in both markets. This ordering did not generalise monotonically across the state range or through time: rank associations were only `+0.0589/+0.0649` in BTC and `+0.0247/+0.0516` in ETH, and the fold/year signs were unstable.

## Fold and year breadth

| Market | Positive gross folds | Positive adverse folds | Positive gross years | Positive adverse years |
|---|---:|---:|---:|---:|
| BTC-USDT | 1/6 | 2/6 | 1/3 | 1/3 |
| ETH-USDT | 2/6 | 2/6 | 1/3 | 2/3 |

BTC supported only one positive gross fold and two positive adverse folds. ETH supported two of each. Both markets had no positive-trend observations in fold 3; BTC also had only five active observations in fold 4, which failed the frozen minimum-support rule. BTC passed only one of three years for each target. ETH passed one gross year and two adverse years, still failing the joint year gate.

## Failure mechanism

The experiment separated a sample-design repair from an information failure:

- Daily sampling increased support from 32/39 weekly observations to 246/272 active daily observations and produced 100% valid dependence draws.
- Older regimes had better high-versus-low mean returns, but the relation was not smoothly monotonic. A few long regimes generated the median ordering while within-fold slopes often turned negative.
- The 2023 sample, containing most active observations, had negative gross slopes in both markets and negative adverse slopes in both markets.
- ETH's gross slope across all observations was effectively zero and slightly negative (`-0.0083%` per state standard deviation).
- All dependence-aware lower bounds crossed zero, so the observed age ordering cannot authorise sizing or selection.

Trend survival age is therefore descriptive of a small number of long-lived regimes, not stable bilateral next-day magnitude information.

## Correctness and replay

The source hashes matched the immutable artifacts, the parsed prefixes were contiguous confirmed 1H grids, every decision used completed own-instrument history, targets used next-open chronology, every sleeve charged exactly two one-way 5 bps transitions, and OOS was not parsed. A complete second run was byte-identical:

```text
evidence SHA-256  d19e435a11d77e0de92502467c2c31de2b325fa82de8ce002c7144d79255f990
```

## Verdict

```text
reject_daily_positive_trend_age_opportunity_premise
```

No age threshold, direction reversal, interaction term, alternate transform, horizon, target, smoothing, market substitution, OOS evaluation, executable candidate, paper promotion or live authority is authorised.

**Remaining blocker:** continuous price-path states tested so far either lack active-state support or produce weak, regime-dependent ordering. Before introducing another information channel, the research programme must determine whether the underlying B1-long next-day opportunity is sufficiently stationary across independent positive regimes to support any causal selector or sizing overlay at all.

**Next strategy experiment:** preregister one training-only **positive-regime opportunity-stationarity closure diagnostic**. Partition every completed daily B1-long decision into its causal contiguous positive 2,160H trend regime, retain the same non-overlapping next-24H gross/net opportunity and adverse-excursion labels, and test whether economic value is broad across regimes rather than concentrated in one or two episodes. Report profitable-regime breadth, regime-level payoff concentration, leave-one-regime-out mean and downside stability, within-regime serial dependence, and a regime-cluster bootstrap independently for BTC and ETH. Authorise no further B1-conditioned selector or sizing search unless both markets show positive median regime payoff, positive lower confidence bounds after leaving each regime out, and no dominant-regime concentration. This is an architecture-eligibility test, not another transform of endpoint direction, margin, path shape, elapsed time, volatility or volume.
