# Variance-ratio persistence risk state — terminal report

## Frozen experiment

```text
family          variance-ratio-persistence-risk-state-1h-v1
candidate count 1
parameter grid  0
issue           #720
parent          5a0fcc97d1a882f8223656c51f5bb8055f534e38
bar             1H
fee             exactly 5 bps one way
verdict         reject_exact_variance_ratio_persistence_risk_state_family
```

The candidate retained immediate full entry into every positive daily 2,160H endpoint trend. At completed 00:00 UTC decisions it used the latest 720 hourly log returns to compute a 24H variance ratio. A negative latest-168H return with `VR24 < 1` reduced exposure to 0.5; a positive latest-168H return with `VR24 > 1` restored 1.0; ambiguous states retained the previous exposure. Decisions executed at the next hourly open.

## Immutable data and sample

| Item | Frozen value |
|---|---|
| Provider | Public OKX SPOT |
| Markets | BTC-USDT and ETH-USDT independently |
| Source rows | 43,930 per artifact |
| Scored prefix | First 43,441 confirmed contiguous 1H bars |
| Training | `[2,880,17,520)` |
| Development OOS | `[17,520,43,440)` |
| Full scored | `[2,880,43,440)` |
| Breadth | 12 contiguous 2,160H folds plus calendar years |
| Uncertainty | 5,000 paired non-circular 168H moving blocks; seed 20260731 |
| Later suffix | Excluded from all metrics; used only for causal prefix-invariance verification |

Artifact IDs were 8685574446 for BTC and 8685572234 for ETH. Full CSV SHA-256 values were `f967995a6acd5c4acd0a17dd030f02cd55441b3f83716e5a4118a58af71ca96e` and `ff53337ffbeafd237703ef6ff5f61a2e0b15df1fbd5954c17a8557e80324e907`.

## Training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC | Candidate | -36.48% | -0.813 | -54.84% | 31.0 | 1.55% | -124.56 bps |
| BTC | B1 | -41.29% | -0.840 | -55.92% | 28.0 | 1.40% | -159.81 bps |
| ETH | Candidate | -33.38% | -0.576 | -51.62% | 27.5 | 1.38% | -114.88 bps |
| ETH | B1 | -40.59% | -0.584 | -56.95% | 23.0 | 1.15% | -168.77 bps |

## Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC | Candidate | +92.76% | +0.996 | -19.24% | 54.5 | 2.73% | 138.15 bps |
| BTC | B1 | +119.68% | +0.954 | -26.55% | 45.0 | 2.25% | 212.75 bps |
| ETH | Candidate | +63.18% | +0.651 | -47.30% | 39.0 | 1.95% | 171.20 bps |
| ETH | B1 | +74.52% | +0.646 | -47.77% | 30.0 | 1.50% | 283.58 bps |

## Full scored sample

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC | Candidate | +22.43% | +0.297 | -54.84% | 85.5 | 4.28% | 42.90 bps |
| BTC | B1 | +28.97% | +0.332 | -55.92% | 73.0 | 3.65% | 69.85 bps |
| ETH | Candidate | +8.72% | +0.223 | -51.62% | 66.5 | 3.33% | 52.90 bps |
| ETH | B1 | +3.68% | +0.233 | -56.95% | 53.0 | 2.65% | 87.28 bps |

## OOS breadth and uncertainty

| Market | Profitable folds | Profitable years | Improved folds/years vs B1 | Residual Sharpe | Annualized mean delta 95% | Sharpe delta 95% |
|---|---:|---:|---:|---:|---:|---:|
| BTC | 5/12 | 3/4 | 3/12; 1/4 | -0.537 | [-20.00%, +8.09%] | [-0.274, +0.404] |
| ETH | 6/12 | 3/4 | 7/12; 1/4 | -0.383 | [-23.84%, +11.73%] | [-0.380, +0.398] |

Both markets produced three profitable calendar years but failed the required 7/12 profitable-fold threshold. Both residual Sharpes were negative, and all dependence-aware mean-return lower bounds were negative.

## Failure mechanism

### BTC

```text
effective risk transitions          18
effective recovery transitions      10
half-state hours                    8833
full-equivalent hours removed       4416.5
half-state arithmetic market carry  +39.94%
market carry removed                +19.97%
incremental fees versus B1          +0.47%
arithmetic candidate-minus-B1       -20.45%
half-state conditional Sharpe       +0.898
full-state conditional Sharpe       +1.843
```

Risk transitions were followed by a mean next-168H market return of +3.49%, with 66.7% positive observations.

### ETH

```text
effective risk transitions          14
effective recovery transitions      9
half-state hours                    6144
full-equivalent hours removed       3072.0
half-state arithmetic market carry  +35.71%
market carry removed                +17.86%
incremental fees versus B1          +0.45%
arithmetic candidate-minus-B1       -18.31%
half-state conditional Sharpe       +0.768
full-state conditional Sharpe       +1.099
```

Risk transitions were followed by a mean next-168H market return of +1.54%, with 57.1% positive observations.

The candidate correctly separated lower-quality from higher-quality trend exposure: the half state had lower conditional Sharpe than the full state in both markets. The economic sign was still wrong for position reduction. Half-state exposure retained positive aggregate carry in both markets, so reducing it removed 19.97 percentage points of BTC arithmetic carry and 17.86 points of ETH carry before the additional transition fees.

BTC also began OOS in an inherited half-risk state. The initial diagnostic would have attributed all 8,833 half-state hours to OOS trigger events. The terminal diagnostic repaired this by separating 49 inherited boundary hours from 8,784 hours initiated inside OOS. No strategy position, return, fee, fold, bootstrap result, gate, or verdict changed.

Both complete executions produced byte-identical machine results:

```text
result.json SHA-256
efed0728fda2e35371758a229e14072f9c477e84e08f12570795afb1717ccc81
```

## Verdict

```text
reject_exact_variance_ratio_persistence_risk_state_family
```

BTC failed OOS return, turnover, edge per turnover, fold breadth, residual Sharpe, and both uncertainty gates. ETH failed the same gates. Sharpe and drawdown point estimates improved slightly in both markets, but not enough to compensate for lost positive trend carry and higher turnover.

No same-interval change to the 720H window, 24H variance-ratio horizon, theoretical boundary, 168H return condition, exposure fraction, hysteresis, cadence, fee, sample, or market-specific treatment is authorized. There is no paper, G1, or live-trading nomination.

## Remaining blocker and next experiment

**Remaining blocker:** magnitude-sensitive serial-dependence states identify relative trend quality but not negative expected carry. Recurrent partial de-risking therefore lowers drawdown while systematically giving up profitable exposure and consuming edge through extra transitions.

**Next strategy experiment:** one own-history-only **trend-margin renewal-count state** that leaves every positive 2,160H trend fully invested and changes only the exit timing. At the first non-positive base decision, retain a fixed 0.5 sleeve for 24H only when the endpoint margin was positive on at least five of the prior seven daily decisions; otherwise exit directly. Restore full exposure on immediate recross and exit the sleeve after one day if the base remains non-positive. One candidate, no grid, no market-specific rule, and no recurrent within-trend sizing. This tests persistence of the base state itself rather than another proxy for conditional trend quality.
