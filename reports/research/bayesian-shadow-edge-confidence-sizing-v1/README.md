# Bayesian shadow-edge confidence sizing v1

## Verdict

`rejected_exact_family_cooldown`

This development-only experiment compared the unchanged canonical walk-forward strategy (`B0`) with one frozen sizing overlay (`B1`). `B1` multiplies the canonical target by

```text
max(0, 2 * Phi(sqrt(720) * mean(B0_net_720) / sample_std(B0_net_720)) - 1)
```

using exactly the preceding 720 completed hourly net returns of the non-recursive `B0` shadow path. Positions remain one-bar delayed and all absolute position changes pay exactly 5 bps one-way.

## Evidence

- Source workflow: `30347175588`
- Source head: `d7cc15839755484b682d6e9094298b8a32f70230`
- BTC artifact: `8683465243`, ZIP SHA-256 `e9bdc2cee531f0b71539a6f4c2b306f2ae702e64bbbe8443ec16bf69c558147a`
- ETH artifact: `8683462187`, ZIP SHA-256 `1f865024ae9d3ce7aa51bfe72bbab054b0377eef01780c75f60f6e8aa2cdc51e`
- Sample: 25,920 confirmed 1H OOS observations and 12 non-overlapping 2,160H folds per market, 2023-07-24 through 2026-07-07 UTC
- Candidate budget: one architecture family, one alternative, 48 policy-fold evaluations
- Fee: exactly 5 bps one-way
- Untouched evidence consumed: false

## Point estimates

| Market | Policy | Net return | Sharpe | Calmar | Max drawdown | Annual turnover | Edge/turnover | Profitable folds |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC | B0 | 43.59% | 0.6369 | 0.4845 | -26.84% | 45.23 | 33.18 bps | 4/12 |
| BTC | B1 | 30.13% | 0.7083 | 0.5592 | -16.65% | 43.63 | 22.63 bps | 6/12 |
| ETH | B0 | 16.31% | 0.3425 | 0.1805 | -29.03% | 62.38 | 12.05 bps | 5/12 |
| ETH | B1 | 24.58% | 0.6064 | 0.5016 | -15.37% | 34.64 | 24.20 bps | 5/12 |

B1 reduced tail loss, turnover, fees and exposure in both markets. BTC nevertheless lost 13.46 percentage points of compounded net return and 10.55 bps of edge per turnover. BTC B1 positive-fold return was also concentrated: the largest positive fold contributed 72.75% of positive-fold return. Relative Sharpe versus the unchanged simple-trend benchmark remained negative in both markets (`-0.7792` BTC, `-0.4828` ETH).

The multiplier was zero in 60.32% of BTC hours and 64.46% of ETH hours. Confidence had essentially no rank association with next-hour B0 net return: Spearman rho `0.0047` for BTC and `0.0093` for ETH.

## Adjusted uncertainty

The confirmatory family used 5,000 paired, non-circular 168H moving-block resamples within folds, preserving each fold-boundary row exactly once and using identical time indices across markets. A methodological flaw was repaired before publication: raw percentile-bootstrap frequencies were not called p-values. Inference uses centered bootstrap errors, basic intervals, one-sided lower bounds and Holm familywise adjustment.

| Endpoint | Observed B1-B0 | One-sided 95% lower bound | Holm-adjusted p |
|---|---:|---:|---:|
| BTC Sharpe | +0.0714 | -0.6104 | 1.0000 |
| BTC edge/turnover | -10.55 bps | -45.17 bps | 1.0000 |
| ETH Sharpe | +0.2639 | -0.4182 | 1.0000 |
| ETH edge/turnover | +12.16 bps | -18.21 bps | 1.0000 |

The frozen rule required every adjusted lower bound to be strictly positive. None passed. Numeric Deflated Sharpe and PBO were not calculated because the repository-wide independent-family count and a mathematically valid complete candidate-by-split matrix are unavailable.

## Validation

- Both ZIP digests matched the published artifact digests.
- All 13 manifest files in each artifact passed SHA-256 verification.
- Canonical target reconstruction error: `1.11e-16` BTC and `3.89e-15` ETH.
- B0 fee and net-return reconstruction errors were below `1e-16`.
- B1 fee, net-return and fold-boundary position reconstruction errors were exactly zero.
- Exact 720-observation windows and one-bar timing passed.
- Future-suffix mutations left all earlier targets and confidence states unchanged.
- Two complete executions produced byte-identical JSON.

## Cooldown

The exact `720H trailing B0 net-return / plug-in Gaussian sign confidence / max(0, 2Phi(z)-1) / multiplicative exposure / hourly update / zero-confidence fail-closed` family must not be rescued on the same BTC/ETH development evidence by changing its lookback, prior, transform, floor, threshold, smoothing, update interval or combining it with another overlay.
