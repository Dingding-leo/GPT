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

Issue #806 established that positive-trend age had adequate daily support but no stable
next-day information. This run tested the more fundamental premise required by any future
B1-conditioned selector or sizing overlay: whether the fixed daily 2,160H endpoint-trend long
state has broad positive opportunity across independent causal positive regimes.

At every completed `00:00 UTC` bar:

```text
B1_t = 1[close_t > close_(t-2160H)]
```

A regime is one maximal contiguous sequence of positive daily B1 decisions, constructed from
completed same-instrument history. Every scored active decision retained its causal regime
identity. A regime already active at the training boundary was retained and marked
left-censored; no regime was dropped, split, duration-filtered, reweighted, or selected after
performance was viewed.

Each active decision used the same independent, consecutive, non-overlapping 24H long-opportunity
label as issue #806:

```text
q         = t, ..., t+23
hourly_rq = open_(q+2) / open_(q+1) - 1
gross     = sum(hourly_rq)
turnover  = 2
net       = gross - 0.0005 * turnover
adverse   = minimum cumulative gross path including initial zero
```

These are diagnostic target labels, not an executable strategy that re-enters and liquidates
daily.

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

The complete immutable CSV hash was verified before parsing only the first 17,520 rows. Training
was `[2,880,17,520)`; development OOS `[17,520,43,440)` and every later row remained unread.
Every target terminal open remained strictly inside training.

No cross-sectional ranking, asset selection, pairs, spreads, cointegration, market-neutral or
long-short portfolio, short position, leverage, private endpoint, credential, account, order,
synthetic data, or 15-minute input was used.

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

The turnover and fees below belong only to independent target sleeves used to label opportunity.

## Daily target-label economics

| Market | Mean gross | Mean net | Mean adverse | Gross-positive days | Net-positive days | Turnover | Embedded fees |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | -0.1781% | -0.2781% | -1.6394% | 112/246 | 107/246 | 492 | 24.60% |
| ETH-USDT | -0.1368% | -0.2368% | -2.0030% | 128/272 | 126/272 | 544 | 27.20% |

The day-weight pooled opportunity was negative before fees in both markets. A selector would
therefore need to isolate a stable minority of regimes rather than modulate a broadly positive
base state.

## Regime breadth and central tendency

| Market | Regimes | Duration min / Q1 / median / Q3 / max | Positive mean-gross | Positive mean-net | Median gross | Median net | Median adverse | Equal-weight gross | Equal-weight net |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 15 | 1 / 2.5 / 4 / 11.5 / 153 | 4/15 | 3/15 | -1.0067% | -1.1067% | -1.9279% | -1.3913% | -1.4913% |
| ETH-USDT | 12 | 2 / 2 / 9 / 20.75 / 131 | 4/12 | 3/12 | -0.4376% | -0.5376% | -2.0301% | -0.2787% | -0.3787% |

Only 26.7% of BTC regimes and 33.3% of ETH regimes had positive mean gross opportunity. Net-positive
breadth fell to 20.0% and 25.0%. Both the median regime and equal-regime-weight mean were negative
in both markets, so the result was not caused solely by a few short losing episodes.

The machine-readable regime table now includes every frozen per-regime field: first and last
scored anchor, censoring, duration, mean and median gross/net, cumulative gross/net, mean adverse
excursion, gross/net positive-day fractions, lag-1 correlation, and absolute/positive gross
contribution shares.

## Concentration and leave-one-regime-out stability

| Market | Max absolute-gross share | Max positive-gross share | Dominant positive regime | Minimum LOO equal gross | Minimum LOO equal net | Minimum LOO day gross | Minimum LOO day net |
|---|---:|---:|---|---:|---:|---:|---:|
| BTC-USDT | 22.74% | **75.75%** | regime 11, 14 Jan–15 Jun 2023 | -1.5135% (omit 12) | -1.6135% (omit 12) | -0.7390% (omit 11) | -0.8390% (omit 11) |
| ETH-USDT | 26.18% | **62.42%** | regime 4, 9–24 Jan 2023 | -0.4902% (omit 7) | -0.5902% (omit 7) | -0.2943% (omit 8) | -0.3943% (omit 8) |

BTC's 153-day January–June 2023 regime supplied 75.75% of all positive cumulative gross
contribution. ETH's 16-day January 2023 regime supplied 62.42%. Both breached the frozen 50%
positive-contribution cap. Removing any single regime could not reveal a broad positive remainder;
the worst equal-regime and day-weight leave-one-out means remained negative before fees in both
markets.

## Complete-regime cluster uncertainty

Uncertainty used 5,000 complete-regime cluster resamples with replacement, seed `20260731`. Every
selected cluster retained its complete observed ordered daily label sequence. All draws were valid.

| Market | Equal gross 95% CI | Equal net 95% CI | Day gross 95% CI | Day net 95% CI | Median gross 95% CI | Median net 95% CI |
|---|---|---|---|---|---|---|
| BTC-USDT | **[-2.7150%,-0.5099%]** | **[-2.8150%,-0.6099%]** | [-1.2626%,+0.0738%] | **[-1.3626%,-0.0262%]** | [-1.8164%,+0.0711%] | **[-1.9164%,-0.0289%]** |
| ETH-USDT | [-0.8832%,+0.3886%] | [-0.9832%,+0.2886%] | [-0.5863%,+0.1829%] | [-0.6863%,+0.0829%] | [-0.7295%,+0.1076%] | [-0.8295%,+0.0076%] |

The repaired reproducer also persists the three frozen uncertainty diagnostics that were missing
from the initial head:

| Market | Positive-gross regime fraction 95% CI | Positive-net regime fraction 95% CI | Max absolute-contribution share 95% CI |
|---|---|---|---|
| BTC-USDT | [6.67%,53.33%] | [0.00%,40.17%] | [13.46%,31.23%] |
| ETH-USDT | [8.33%,58.33%] | [8.33%,50.00%] | [15.21%,40.17%] |

BTC's regime-balanced gross and net intervals were entirely negative. ETH's intervals crossed
zero, but every lower bound was negative. Neither market established positive dependence-aware
stationarity.

## Fold and year breadth

| Market | Positive gross folds | Positive net folds | Positive gross years | Positive net years |
|---|---:|---:|---:|---:|
| BTC-USDT | 2/6 | 2/6 | 1/3 | 1/3 |
| ETH-USDT | 2/6 | 2/6 | 1/3 | 1/3 |

Both markets were negative in 2021 and 2022 and positive only in 2023. Fold three had no active B1
observations in either market. The frozen requirement was at least `4/6` positive folds and
two-thirds of represented years positive for both gross and net; neither market approached it.

## Within-regime dependence

| Market | Regimes with estimable lag-1 | Median per-regime lag-1 gross correlation | Pooled centred lag-1 gross correlation |
|---|---:|---:|---:|
| BTC-USDT | 9 | -0.2210 | -0.0665 |
| ETH-USDT | 6 | -0.2090 | -0.1675 |

Daily opportunity was mildly mean-reverting within regimes rather than positively persistent.
This makes elapsed regime membership an especially weak basis for increasing exposure and
supports complete-regime rather than iid-day uncertainty.

## Gate result

Only cluster-bootstrap validity passed in either market.

```text
BTC passed gates  1/10
ETH passed gates  1/10
markets passing   0/2
```

Both markets failed positive median payoff, profitable-regime breadth, equal-weight and day-weight
positive lower bounds, both leave-one-regime-out gates, positive-contribution non-dominance, fold
breadth, and year breadth.

## Correctness repair

Inspection of the first PR head found that the persisted reproducer did not emit all statistics
frozen in issue #808. The final head repairs that evidence gap without changing any source row,
label, fee, point estimate, gate, or verdict:

1. every regime now persists median gross/net, positive-day fractions, and contribution shares;
2. leave-one-regime-out minima now identify the omitted regime;
3. duration Q1/Q3 and median regime adverse excursion are persisted;
4. pooled within-regime centred lag-1 correlation is generated rather than report-only;
5. bootstrap uncertainty now includes positive-regime fractions and maximum absolute contribution
   share, with finite-draw validation.

Two complete local reconstructions from the immutable artifacts were byte-identical.

```text
evidence JSON SHA-256        66caad6961b286ee4f58f7c0ad7b2b1ac226fd981901bbc0094e366ef4f1e537
evidence gzip SHA-256        c9d474279c313a0a4210ddc3949555f39b749eecbc979813229916ebbf19bcab
evidence base64 SHA-256      6c55bf2742648b802bfff63a9b6bcbfbc2beb784b80b3d48a22046a3de954cc0
```

## Failure mechanism

The closure diagnostic separates three defects in the endpoint-sign channel:

1. **Negative base opportunity:** pooled next-day gross opportunity during B1-positive states was
   negative in both markets before fees.
2. **Poor regime breadth:** only four regimes per market had positive mean gross opportunity, and
   only three survived the 10 bps independent-sleeve round trip.
3. **Episode concentration:** most positive cumulative contribution came from one 2023 regime in
   each market, while 2021–2022 and four of six complete folds were negative or inactive.

The age result in issue #806 was therefore not concealing a stable nonlinear selector
relationship. It described heterogeneous episodes inside an endpoint-sign architecture whose
positive-state opportunity is not broad enough to support further same-channel overlay search.

## Verdict

```text
reject_positive_regime_opportunity_stationarity_premise
```

No regime exclusion, duration threshold, weighting change, alternate horizon, endpoint transform,
B1-conditioned selector, B1-conditioned sizing rule, market substitution, OOS evaluation, paper
promotion, or live authority is authorised.

**Remaining blocker:** the fixed 2,160H endpoint-sign architecture does not supply broad positive
next-day opportunity across independent regimes. Further overlays would search for a small set of
historical episodes rather than repair a stable base edge.

**Next strategy experiment:** after exact rejected-family de-duplication, preregister one
fresh-cohort **causal local-linear-trend state-space architecture** that replaces—not conditions—the
endpoint sign. At a fixed weekly cadence, estimate each instrument's latent level and slope from
its own completed 1H history with one frozen robust process/observation-noise contract, and map a
positive posterior lower bound on next-week latent drift above the known fee hurdle to long,
otherwise cash. Use one candidate, zero grid, immutable public 1H data, exactly 5 bps one way, and
full train/OOS/fold/year/cluster-uncertainty gates. No B1 feature, age, margin, persistence,
volatility threshold, or same-market rescue variant is permitted.
