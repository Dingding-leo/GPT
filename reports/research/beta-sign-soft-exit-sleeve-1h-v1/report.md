# Beta-sign soft exit sleeve — terminal rejection

```text
Family          beta-sign-soft-exit-sleeve-1h-v1
Candidate count 1
Parameter grid  0
Fee             exactly 5 bps one way
Fresh cohort    SOL-USDT and XRP-USDT
Issue / PR      #757 / #758
Source head     f7c069d5f6a1dfdc9e4ac00d8324f487cb1f69c3
Main parent     5a0fcc97d1a882f8223656c51f5bb8055f534e38
Verdict         reject_beta_sign_soft_exit_sleeve_family
```

## Strategy change

The daily 2,160H endpoint-trend benchmark remains fully long while its own completed signal is positive. At the first positive-to-non-positive transition, the candidate retains one fixed fractional sleeve for at most 168H. Its exposure is determined only by prior completed same-instrument exit episodes:

```text
posterior probability = (prior wins + 1) / (prior episodes + 2)
sleeve exposure       = 0.5 × posterior probability
```

A win is a positive hypothetical 0.5-sleeve target: `0.5 × arithmetic open-to-open carry + 0.0005` when the episode terminates on a base recross, otherwise `0.5 × carry` at exact 168H expiry. The posterior is updated only after terminal execution and is never reset. Every decision is same-instrument, causal, daily, and executed at the next hourly open.

## Immutable data and sample

| Item | Frozen specification |
|---|---|
| Provider | Public confirmed OKX SPOT |
| Markets | SOL-USDT and XRP-USDT independently, fixed before acquisition |
| Workflow | `30599723593`, successful exact source-acquisition head |
| Artifacts | SOL `8781469963`; XRP `8781477440` |
| Artifact SHA-256 | SOL `082b96bdd3bdec5f80b7fd68949ae588a77ddd392d733528790400bc725b699a`; XRP `05b884d52cfe7aeaef3bfe116e6875cf1cbe70a486600993cece57fa9dc7316c` |
| Source rows | 43,994 per market |
| Frozen prefix | First 43,441 contiguous confirmed 1H rows |
| Frozen span | 24 July 2021 00:00 through 8 July 2026 00:00 UTC |
| Training | `[2,880,17,520)` |
| Development OOS | `[17,520,43,440)` |
| Full scored | `[2,880,43,440)` |
| Breadth | 12 contiguous 2,160H folds and four calendar years |
| Uncertainty | 5,000 paired non-circular 168H moving blocks, seed `20260731` |
| Execution | Completed daily 00:00 UTC bar → next hourly open |

- SOL-USDT full source SHA-256 `321c1180674db5c577357f636a3e8caacb6052953e0007f77fc4947c00c1c744`; canonical frozen CSV SHA-256 `ef992540deef5208474cc8a7c60ae7a0e9b5c44efcdb85d210baee79da21ceec`.
- XRP-USDT full source SHA-256 `16de43751adf14d1274ff5656506f62c2dd5250a0029a11059b419de7d354cdb`; canonical frozen CSV SHA-256 `896125b2d27a9be552cd2d00c41a1a50d692ff5d0163253950166c6e6e2400a2`.

All frozen timestamps were unique, exactly one hour apart, confirmed, and positive-valued. The 553-row later suffix was excluded from signals, scoring, posterior updates, and uncertainty.

## Training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| SOL | Candidate | -69.02% | -1.243 | -72.58% | 25.64 | 1.28% | -383.69 bps |
| SOL | Daily B1 | -69.79% | -1.305 | -73.27% | 30.00 | 1.50% | -338.47 bps |
| SOL | Hourly B0 | -58.38% | -0.860 | -65.15% | 144.00 | 7.20% | -47.68 bps |
| XRP | Candidate | -57.10% | -0.718 | -65.96% | 30.92 | 1.55% | -201.10 bps |
| XRP | Daily B1 | -56.25% | -0.712 | -65.09% | 37.00 | 1.85% | -164.40 bps |
| XRP | Hourly B0 | -45.18% | -0.402 | -67.83% | 161.00 | 8.05% | -22.48 bps |

## Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| SOL | Candidate | +213.87% | 0.902 | -57.63% | 40.33 | 2.02% | +463.53 bps |
| SOL | Daily B1 | +171.23% | 0.832 | -58.40% | 53.00 | 2.65% | +323.48 bps |
| SOL | Hourly B0 | +209.77% | 0.897 | -54.97% | 199.00 | 9.95% | +92.93 bps |
| XRP | Candidate | -7.77% | 0.272 | -65.36% | 50.56 | 2.53% | +99.87 bps |
| XRP | Daily B1 | -26.58% | 0.144 | -69.15% | 61.00 | 3.05% | +43.31 bps |
| XRP | Hourly B0 | -3.38% | 0.295 | -67.16% | 323.00 | 16.15% | +16.89 bps |

## Full scored sample

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| SOL | Candidate | -2.75% | 0.305 | -81.35% | 65.97 | 3.30% | +134.25 bps |
| SOL | Daily B1 | -18.05% | 0.242 | -82.25% | 83.00 | 4.15% | +84.22 bps |
| SOL | Hourly B0 | +28.91% | 0.401 | -75.37% | 343.00 | 17.15% | +33.90 bps |
| XRP | Candidate | -60.43% | -0.043 | -85.12% | 81.48 | 4.07% | -14.35 bps |
| XRP | Daily B1 | -67.88% | -0.127 | -86.53% | 98.00 | 4.90% | -35.11 bps |
| XRP | Hourly B0 | -47.03% | 0.067 | -78.52% | 484.00 | 24.20% | +3.79 bps |

## OOS benchmark comparison

**SOL-USDT:** net return changed by `+42.64` percentage points, Sharpe by `+0.070`, maximum drawdown by `+0.77` points, turnover by `-12.67`, and edge per turnover by `+140.05` bps.
**XRP-USDT:** net return changed by `+18.81` percentage points, Sharpe by `+0.128`, maximum drawdown by `+3.80` points, turnover by `-10.44`, and edge per turnover by `+56.55` bps.

SOL improved every benchmark-relative OOS point gate and remained strongly profitable, but its full-sample return was negative. XRP improved every benchmark-relative OOS point gate but still lost money both OOS and over the full scored sample. The overlay therefore reduced damage and improved efficiency; it did not establish a viable bilateral long/cash architecture.

## Breadth and uncertainty

| Market | Profitable folds | Improved folds | Profitable years | Improved years | Positive-fold concentration | Residual Sharpe | Mean Δ 95% | Sharpe Δ 95% |
|---|---:|---:|---:|---:|---:|---:|---|---|
| SOL | 6/12 | 6/12 | 2/4 | 3/4 | 72.99% | +0.671 | [-3.21%, +13.60%] | [-0.051, +0.193] |
| XRP | 4/12 | 7/12 | 1/4 | 3/4 | 92.44% | +0.878 | [-0.36%, +18.29%] | [-0.009, +0.298] |

Common-index bilateral inference was positive but insufficient for the preregistered per-market gates:

```text
Median annualised mean-return delta  +6.69%
95% interval                         [+0.29%, +13.86%]
Median Sharpe delta                  +0.099
95% interval                         [+0.002, +0.211]
Markets passing every gate           0/2
```

Neither market reached seven profitable folds or three profitable years. Every individual-market dependence-aware lower bound remained below zero. SOL concentrated 72.99% of positive fold return in one fold; XRP concentrated 92.44%.

## Failure mechanism

### SOL-USDT

```text
OOS episode starts                 26
Wins / losses                      19 / 7
Recrosses / expiries               19 / 7
Mean sleeve exposure               0.3275
Completed-episode contribution     +16.23%
Boundary-open partial contribution -0.72% over 23H
Total arithmetic residual vs B1    +15.50%
```

SOL episode signs became favourable OOS: 19 of 26 completed starts were wins, and the soft sleeve contributed positive arithmetic timing. However, one late May–June 2026 expiry contributed approximately `−7.96%`, and the still-open final sleeve lost another `−0.72%` before the frozen boundary. The candidate finished only six folds and two years profitable, while the weak training base left the full sample at `−2.75%`.

### XRP-USDT

```text
OOS episode starts                 31
Wins / losses                      20 / 11
Recrosses / expiries               18 / 13
Mean sleeve exposure               0.2906
Completed-episode contribution     +24.07%
Total arithmetic residual vs B1    +24.07%
```

XRP also showed positive benchmark-relative episode economics: 20 of 31 OOS starts were wins and completed sleeves contributed `+24.07%` arithmetically. The improvement was concentrated around a small number of 2024–2025 rebound episodes. Four of twelve folds and one of four years were profitable; even after the overlay, OOS return was `−7.77%` and full return was `−60.43%`.

The posterior did what it was designed to do—retain more exposure as the observed win rate rose, lower turnover, and improve B1-relative efficiency. The rejected hypothesis was stronger: that this would produce bilateral absolute viability, temporal breadth, and positive per-market uncertainty lower bounds. It did not.

## Diagnostic repair

The initial result writer persisted environment-specific absolute source paths and attributed only completed OOS episodes. SOL had one sleeve that began at interval `43,417` and remained open at the frozen scored boundary `43,440`, leaving 23 observed hours outside the completed-episode attribution.

The terminal reproducer stores source basenames and explicitly separates completed-episode contribution from a boundary-open partial contribution. SOL now reconciles `+16.2252%` completed contribution plus `−0.7237%` boundary partial contribution to the exact `+15.5015%` arithmetic candidate-minus-B1 residual. XRP reconciles `+24.0729%` with no boundary-open episode. Identity errors are below `3e-17`. No signal, exposure, return, fee, metric, bootstrap draw, gate, or verdict changed. Two terminal runs were byte-identical.

## Verdict

```text
reject_beta_sign_soft_exit_sleeve_family
```

Both markets passed benchmark-relative OOS net, Sharpe, drawdown, turnover, edge-per-turnover, and residual-Sharpe point gates. Both failed profitable-fold breadth, profitable-year breadth, both individual uncertainty lower-bound gates, and positive full-sample return. XRP additionally remained negative OOS in absolute terms.

No same-cohort change to the prior, sizing map, win definition, sleeve horizon, base lookback, fee, cadence, or market treatment is authorised. There is no canonical strategy change, G1 nomination, paper promotion, or live-trading authorisation.

## Evidence identities

```text
Protocol SHA-256   df10154d7106b2ee10533d7ae10b867fcdcb72399d361e785d393d2e5dbc6271
Reproducer SHA-256 bafebc7c8edb5a7d084aabb7c4506e35feb3a1b82e6146a0995e4cf2603bf509
Result SHA-256     2a45c859ebf38ea2d7afe9876049bfff63842e27ff3a331892b1c26516afa492
Canonical payload  a96f2d2c1310f081d1946e3121e036d549ebd7f296ebc305d8cb673dbaa6d2ec
```

**Remaining blocker:** the post-exit rebound effect appears benchmark-relative across both fresh markets, but the unconditional 2,160H base architecture is not absolutely viable and the sleeve gains remain temporally concentrated. A posterior over unconditional episode signs cannot distinguish mechanical rolling-reference exits from genuine current-price breakdowns.

**Next strategy experiment:** on another predeclared fresh 1H cohort, test one own-history-only **rolling-reference exit-cause decomposition**. At each first 2,160H base exit, separate the latest 24H change in current close from the contemporaneous 24H change in the lagged 2,160H reference close; permit one fixed half bridge only when reference uplift, rather than current-price decline, caused the crossing. One candidate, no grid, no reuse of SOL/XRP to choose thresholds or sizing.
