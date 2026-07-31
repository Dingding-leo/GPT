# Positive-regime B1 opportunity stationarity premise rejected

```text
family          positive-regime-opportunity-stationarity-closure-1h-v1
classification  training-only architecture-eligibility closure diagnostic
candidate count 0
diagnostic count 1
parameter grid  0
markets         BTC-USDT and ETH-USDT independently
bar             immutable public confirmed OKX SPOT 1H
fee             exactly 5 bps one way inside each independent target sleeve
OOS accessed    no
markets passing 0/2
verdict         reject_positive_regime_opportunity_stationarity_premise
```

## Strategy-facing objective

Issue #806 established that positive-trend age had enough daily support but no stable next-day information. This run tested the more fundamental premise required by any future B1-conditioned selector or sizing overlay: whether the fixed daily 2,160H endpoint-trend long state has broad positive opportunity across independent causal positive regimes.

At every completed `00:00 UTC` bar:

```text
B1_t = 1[close_t > close_(t-2160H)]
```

A regime was one maximal contiguous sequence of positive daily B1 decisions, constructed from completed same-instrument history. Every scored active decision retained its causal regime identity. The one regime already active at the training boundary in each market was retained and marked left-censored; no regime was dropped, duration-filtered or split.

Each active decision used the same independent, consecutive and non-overlapping 24H long-opportunity label as issue #806:

```text
q         = t, ..., t+23
hourly_rq = open_(q+2) / open_(q+1) - 1
gross     = sum(hourly_rq)
turnover  = 2
net       = gross - 0.0005 * turnover
adverse   = minimum cumulative gross path including initial zero
```

These are diagnostic target labels, not an executable strategy that re-enters and liquidates daily.

## Immutable data and sample

| Item | BTC-USDT | ETH-USDT |
|---|---:|---:|
| Artifact | `8769605568` | `8769619607` |
| CSV SHA-256 | `40c7ba3dbf64b8b31c634a79e1a2d5e2fa9d60b024c1fd62848d37ed967c13a0` | `0164a5cc1730f70ad9817980d67d6350cf71013cdb759c1a153a66890127d6f8` |
| Parsed rows | 17,520 | 17,520 |
| Eligible daily calendar anchors | 609 | 609 |
| Active B1 anchors | 246 | 272 |
| Scored positive regimes | 15 | 12 |
| Left-censored regimes | 1 | 1 |
| Right-censored regimes | 1 | 0 |
| First / last active anchor | 21 Nov 2021 / 22 Jul 2023 | 21 Nov 2021 / 22 Jul 2023 |

The complete immutable file hash was verified before parsing only the first 17,520 rows. Training was `[2,880,17,520)`; development OOS `[17,520,43,440)` and every later row remained unread. Every target terminal open remained strictly inside training.

## Candidate-performance fields

Candidate count was zero, so no executable path was created.

```text
training return / Sharpe          not computed
development-OOS return / Sharpe   not computed; OOS unread
full-sample return / Sharpe       not computed
B0/B1 strategy benchmark          not applicable
strategy maximum drawdown         not computed
strategy edge per turnover        not applicable
```

The turnover and fee numbers below belong only to independent target sleeves used to label opportunity.

## Daily target-label economics

| Market | Mean gross | Mean net | Mean adverse | Gross-positive days | Net-positive days | Turnover | Embedded fees |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | -0.1781% | -0.2781% | -1.6394% | 112/246 | 107/246 | 492 | 24.60% |
| ETH-USDT | -0.1368% | -0.2368% | -2.0030% | 128/272 | 126/272 | 544 | 27.20% |

The day-weight pooled opportunity was negative before fees in both markets. Therefore a selector would need to identify a genuinely stable minority of regimes rather than merely modulate a broadly positive base state.

## Regime breadth and central tendency

| Market | Regimes | Duration min / median / max | Positive mean-gross regimes | Positive mean-net regimes | Median regime gross | Median regime net | Equal-weight gross | Equal-weight net |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 15 | 1 / 4 / 153 days | 4/15 | 3/15 | -1.0067% | -1.1067% | -1.3913% | -1.4913% |
| ETH-USDT | 12 | 2 / 9 / 131 days | 4/12 | 3/12 | -0.4376% | -0.5376% | -0.2787% | -0.3787% |

Only 26.7% of BTC regimes and 33.3% of ETH regimes had positive mean gross opportunity. Net-positive breadth fell to 20.0% and 25.0%. Both the median regime and equal-regime-weight mean were negative in both markets, so the failure was not caused solely by a few short losing episodes.

## Concentration and leave-one-regime-out stability

| Market | Max absolute-gross share | Max positive-gross share | Dominant positive regime | Minimum LOO equal gross | Minimum LOO equal net | Minimum LOO day gross | Minimum LOO day net |
|---|---:|---:|---|---:|---:|---:|---:|
| BTC-USDT | 22.74% | **75.75%** | 14 Jan–15 Jun 2023 | -1.5135% | -1.6135% | -0.7390% | -0.8390% |
| ETH-USDT | 26.18% | **62.42%** | 9–24 Jan 2023 | -0.4902% | -0.5902% | -0.2943% | -0.3943% |

BTC's 153-day January–June 2023 regime supplied 75.75% of all positive cumulative gross contribution. ETH's 16-day January 2023 regime supplied 62.42%. Both breached the frozen 50% positive-contribution cap.

Removing any one regime could not reveal a broad positive remainder. The worst equal-regime and day-weight leave-one-out means remained negative before fees in both markets.

## Complete-regime cluster uncertainty

Uncertainty used 5,000 complete-regime cluster resamples with replacement, seed `20260731`. Every selected cluster retained its complete observed daily label sequence; all draws were valid.

| Market | Equal-weight gross 95% CI | Equal-weight net 95% CI | Day-weight gross 95% CI | Day-weight net 95% CI | Median-regime gross 95% CI | Median-regime net 95% CI |
|---|---|---|---|---|---|---|
| BTC-USDT | **[-2.7150%,-0.5099%]** | **[-2.8150%,-0.6099%]** | [-1.2626%,+0.0738%] | **[-1.3626%,-0.0262%]** | [-1.8164%,+0.0711%] | **[-1.9164%,-0.0289%]** |
| ETH-USDT | [-0.8832%,+0.3886%] | [-0.9832%,+0.2886%] | [-0.5863%,+0.1829%] | [-0.6863%,+0.0829%] | [-0.7295%,+0.1076%] | [-0.8295%,+0.0076%] |

BTC's regime-balanced gross and net intervals were entirely negative. ETH's intervals crossed zero, but every lower bound was negative. No dependence-aware positive lower-bound gate passed.

## Fold and year breadth

| Market | Positive gross folds | Positive net folds | Positive gross years | Positive net years |
|---|---:|---:|---:|---:|
| BTC-USDT | 2/6 | 2/6 | 1/3 | 1/3 |
| ETH-USDT | 2/6 | 2/6 | 1/3 | 1/3 |

Both markets were negative in 2021 and 2022 and positive only in 2023. Fold three had no active B1 observations in either market. The frozen requirement was at least `4/6` positive folds and two-thirds of represented years positive for both gross and net; neither market approached it.

## Within-regime dependence

| Market | Regimes with estimable lag-1 correlation | Median regime lag-1 gross correlation | Pooled within-regime centred lag-1 correlation |
|---|---:|---:|---:|
| BTC-USDT | 9 | -0.2210 | -0.0665 |
| ETH-USDT | 6 | -0.2090 | -0.1675 |

Daily opportunity was mildly mean-reverting within regimes rather than positively persistent. This makes elapsed regime membership an especially weak basis for increasing exposure and supports the use of complete-regime rather than iid-day uncertainty.

## Gate result

Only cluster-bootstrap validity passed in either market.

```text
BTC passed gates  1/10
ETH passed gates  1/10
markets passing   0/2
```

Both markets failed positive median payoff, profitable-regime breadth, equal-weight and day-weight positive lower bounds, both leave-one-regime-out gates, positive-contribution non-dominance, fold breadth and year breadth.

## Failure mechanism

The closure diagnostic separates three problems:

1. **Negative base opportunity:** pooled next-day gross opportunity during B1-positive states was negative in both markets before fees.
2. **Poor regime breadth:** only four regimes per market had positive mean gross opportunity, and only three survived the 10 bps independent-sleeve round trip.
3. **Episode concentration:** most positive cumulative contribution came from one 2023 regime in each market, while 2021–2022 and four of six complete folds were negative.

The age result in issue #806 was therefore not hiding a stable nonlinear selector relationship. It was describing heterogeneous episodes inside an endpoint-sign architecture whose positive-state opportunity is not broad enough to support further same-channel overlay search.

## Correctness and replay

The reproducer verified exact source hashes, confirmed a contiguous 1H training prefix, constructed regimes only from completed daily states, retained boundary-censored regimes, used next-open chronology, charged exactly two one-way 5 bps transitions per independent label and never parsed OOS. A complete second reconstruction was byte-identical:

```text
evidence JSON SHA-256       4a8188d7048b0a3421fb6974c70a2aa808704a5ea8360390765006f3d45c04dc
evidence gzip SHA-256       1d63b7271b81186e2d14dba7d1ea2f766f49b0e1812517ba7982b8bd694dee41
evidence encoding            deterministic gzip, base64 text in repository
```

## Verdict

```text
reject_positive_regime_opportunity_stationarity_premise
```

No regime exclusion, duration threshold, weighting change, alternate horizon, endpoint transform, B1-conditioned selector, B1-conditioned sizing rule, market substitution, OOS evaluation, paper promotion or live authority is authorised.

**Remaining blocker:** the fixed 2,160H endpoint-sign architecture does not supply broad positive next-day opportunity across independent regimes. Further overlays would be searching for a small set of historical episodes rather than repairing a stable base edge.

**Next strategy experiment:** after exact rejected-family de-duplication, preregister one fresh-cohort **causal local-linear-trend state-space architecture** that replaces—not conditions—the endpoint sign. At a fixed weekly cadence, estimate each instrument's latent level and slope from its own completed 1H history with one frozen robust process/observation-noise contract, and map a positive posterior lower bound on the next-week latent drift above the known fee hurdle to long, otherwise cash. Use one candidate, zero grid, immutable public 1H data, exactly 5 bps one way, and full train/OOS/fold/year/cluster-uncertainty gates. No B1 feature, age, margin, persistence, volatility threshold or same-market rescue variant is permitted.
