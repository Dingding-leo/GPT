# Signed 168H path-coherence opportunity premise rejected

```text
family          signed-path-coherence-opportunity-diagnostic-1h-v1
classification  training-only architecture-eligibility diagnostic
candidate count 0
diagnostic count 1
parameter grid  0
markets         BTC-USDT and ETH-USDT independently
bar             immutable public confirmed OKX SPOT 1H
fee             exactly 5 bps one way inside self-contained target sleeves
OOS accessed    no
markets passing 0/2
verdict         reject_signed_path_coherence_opportunity_premise
```

## Strategy-facing change

This run replaced the rejected zero-inflated boundary-occupancy state with one continuous own-history statistic. At each completed Monday `00:00 UTC` anchor whose complete feature and target windows lay inside training, and only when the carried daily 2,160H B1 state was already long:

```text
coherence_t = log(close_t / close_(t-168)) /
              sum(abs(log(close_j / close_(j-1))), j=t-167..t)
```

Higher coherence represents a smoother positive path; negative values represent an orderly decline despite the slow B1 state remaining long. No threshold, fitted parameter, rank, cross-market input, or executable position rule was introduced.

The next 168H target was a self-contained daily-B1 sleeve from cash, executed next-open. Turnover charged entry, every internal B1 transition, and terminal liquidation at exactly `0.0005` per one-way unit. Primary targets were gross arithmetic opportunity and minimum cumulative gross return, where a higher adverse-excursion value is better.

## Immutable data and sample

| Item | BTC-USDT | ETH-USDT |
|---|---:|---:|
| Artifact | `8769605568` | `8769619607` |
| CSV SHA-256 | `40c7ba3dbf64b8b31c634a79e1a2d5e2fa9d60b024c1fd62848d37ed967c13a0` | `0164a5cc1730f70ad9817980d67d6350cf71013cdb759c1a153a66890127d6f8` |
| Parsed rows | 17,520 | 17,520 |
| Eligible Monday calendar | 85 | 85 |
| B1-long active anchors | 32 | 39 |
| First / last calendar anchor | 29 Nov 2021 / 10 Jul 2023 | 29 Nov 2021 / 10 Jul 2023 |

Only `[0,17,520)` was parsed. Training was `[2,880,17,520)`; development OOS `[17,520,43,440)` and the later suffix remained unread. Every state window satisfied `anchor-167 >= 2,880`, and every target satisfied `anchor+169 < 17,520`.

## Target-sleeve economics

These are labels used to assess information, not returns from a proposed strategy.

| Market | Mean gross | Mean net | Mean adverse excursion | Positive weeks | Turnover | Embedded fees | Mean target exposure |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | -0.4729% | -0.5822% | -5.0095% | 13/32 | 70 | 3.50% | 90.62% |
| ETH-USDT | -0.8613% | -0.9741% | -5.8956% | 16/39 | 88 | 4.40% | 91.21% |

Maximum absolute gross-week concentration was 13.48% for BTC and 12.42% for ETH. No target sleeve was inactive after conditioning on B1 long at the anchor.

Executable training return, Sharpe, maximum drawdown, edge per turnover, B0/B1 strategy comparison, OOS metrics, and full-sample metrics were not computed because candidate count was zero. Per-sleeve adverse excursion is reported instead of candidate drawdown.

## Point estimates and dependence-aware uncertainty

| Market | Gross rho | 95% CI | Adverse rho | 95% CI | Gross slope / state SD | Adverse slope / state SD |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | +0.0077 | [-0.4334,+0.4227] | +0.1158 | [-0.3343,+0.5129] | +0.2225% | +0.5171% |
| ETH-USDT | +0.1204 | [-0.2171,+0.4738] | +0.0858 | [-0.2628,+0.4238] | +0.9615% | **-0.0560%** |

Slope intervals also crossed zero bilaterally:

```text
BTC gross       [-2.4421%, +2.1268%]
BTC adverse     [-0.9103%, +1.4443%]
ETH gross       [-2.2000%, +3.9822%]
ETH adverse     [-1.8452%, +1.2886%]
```

The frozen 5,000 common-calendar, non-circular four-week moving-block resamples produced:

```text
BTC valid draws             4,612 / 5,000 = 92.24%
ETH valid draws             4,962 / 5,000 = 99.24%
common valid draws          4,612 / 5,000 = 92.24%
common median gross rho     +0.0641  95% CI [-0.2966,+0.4189]
common median adverse rho   +0.1008  95% CI [-0.2447,+0.4359]
common median gross slope   +0.5920% 95% CI [-2.0132%,+2.8385%]
common median adverse slope +0.2306% 95% CI [-1.1771%,+1.2482%]
```

BTC and the common panel failed the frozen 95% valid-draw requirement because the active-at-anchor sample was too sparse in some resampled calendar paths. Every lower confidence bound remained below zero.

## State dispersion and median ordering

The information innovation repaired #798's state saturation: coherence retained continuous variation and passed the frozen IQR requirement in both markets.

| Market | Min | Q1 | Median | Q3 | Max | IQR | Low / high observations |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | -0.1515 | -0.0650 | -0.0034 | +0.0917 | +0.3435 | 0.1567 | 16 / 16 |
| ETH-USDT | -0.2329 | -0.0494 | +0.0050 | +0.0749 | +0.2737 | 0.1243 | 20 / 19 |

However, conditioning on B1 long left too little support for the preregistered 20/20 median partition in either market.

| Market | High-minus-low gross | High-minus-low adverse | High-minus-low net |
|---|---:|---:|---:|
| BTC-USDT | +1.7947% | +1.5873% | +1.8009% |
| ETH-USDT | +1.3830% | **-0.6914%** | +1.3567% |

BTC's median split was economically ordered but unsupported and contradicted by a near-zero rank relationship. ETH's high-coherence group had better mean return but a worse adverse excursion, directly failing the downside-control hypothesis.

## Fold and year breadth

| Market | Positive gross folds | Positive adverse folds | Positive gross years | Positive adverse years |
|---|---:|---:|---:|---:|
| BTC-USDT | 2/6 | 3/6 | 2/3 | 2/3 |
| ETH-USDT | 2/6 | 2/6 | 1/3 | 1/3 |

BTC had no active observations in complete folds 3 and 4; ETH had none in fold 3. Only 24 of BTC's 32 active anchors and 32 of ETH's 39 active anchors fell inside the six complete 2,160H folds, with the remainder in the incomplete training tail. Neither market met the frozen `4/6` breadth gate for either target, and ETH failed both year gates.

## Failure mechanism

The continuous state solved the previous feature-engineering defect but not the alpha bottleneck:

- **BTC:** gross rank correlation was effectively zero (`+0.0077`). A favourable median split depended on a small 16/16 sample and did not survive moving-block uncertainty.
- **ETH:** return ordering was weakly positive, but adverse-excursion ordering reversed. Smooth positive recent paths did not protect the next active sleeve from downside.
- **Both:** B1-long conditioning created sparse and regime-clustered support, producing empty folds and insufficient median partitions.
- **Uncertainty:** all individual and common lower bounds crossed below zero; BTC's valid-draw fraction failed closed.

The feature therefore does not provide stable bilateral information for sizing an already-active B1 sleeve.

## Verdict

```text
reject_signed_path_coherence_opportunity_premise
```

No same-sample executable candidate, coherence threshold, alternate horizon, denominator transform, unsigned variant, quantile, smoothing, market substitution, OOS evaluation, paper promotion, or live authority is authorised.

**Remaining blocker:** conditioning only on B1-long weekly anchors removes inactivity contamination but leaves too little temporally broad support. A useful state must be defined continuously on every daily decision and forecast a risk-adjusted next-day opportunity without relying on a sparse weekly active subset.

**Next strategy experiment:** preregister one training-only **daily trend-age interaction diagnostic**. At every completed daily B1-long decision, use one fixed continuous state—the number of consecutive daily decisions since the current positive 2,160H trend began, transformed as `log1p(age_days)`—and test the next 24H active-B1 gross opportunity and adverse excursion. Use all daily active observations, 168H dependence blocks, no thresholds, no OOS, and no executable candidate unless bilateral magnitude, uncertainty, fold/year breadth, and state-support gates pass.
