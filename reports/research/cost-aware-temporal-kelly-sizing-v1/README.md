# Cost-aware temporal Kelly sizing v1 — rejected

Issue: #571  
Base policy: fixed `2160H simple_trend_long_cash`, observed next-open to next-open  
Candidate count: 1  
Fee: exactly 5 bps one-way

## Frozen policy

For every completed 1H decision bar `t`, update an expanding Welford estimator using only already observed open-to-open returns whose causally preceding fixed trend target was long:

```text
include g_s = open_(s+1) / open_s - 1 only when b_(s-1) == 1 and s <= t
predictive_variance_t = sample_variance_t * (1 + 1/n_t)
k_t = clip(mu_t / (4 * predictive_variance_t), 0, 1)
```

`k_t` is quarter Kelly. When the base target is cash, K1 is forced to cash. When the base target is long, K1 compares the current committed position with `k_t` using:

```text
U_t(p) = p*mu_t - 2*p^2*predictive_variance_t - 0.0005*abs(p-p_prev)
```

It moves only when the candidate utility is strictly larger. No rolling window, floor, threshold, smoothing, alternative Kelly fraction or rescue candidate was searched.

## Data and reconstruction

- Immutable public confirmed OKX 1H artifacts from workflow `30347175588`.
- BTC artifact `8685574446`; ZIP SHA-256 `d36b151d0279e552f0f561403647ca8495febf6bd7c87c0b85cf0e7ad3df6119`.
- ETH artifact `8685572234`; ZIP SHA-256 `e32884abe83663b36bc52ce4f4b3cc60b03bb2f4f2948853134dc6831706a9bb`.
- All 13 manifest-bound files passed per market.
- Evaluation: 25,920 hours per market, `2023-07-24 00:00 UTC` through `2026-07-07 23:00 UTC`, 12 consecutive 2,160H folds.
- Initial evaluation position was cash; estimator history was causal and positions carried across folds and years.

The independently reconstructed next-open baseline matched the merged canonical benchmark exactly for total return, Sharpe and turnover in both markets.

## Results

| Market | Policy | Net return | Sharpe | Calmar | Max drawdown | ES 1% | Annual turnover | Edge/turnover | Adjustments | Time positive |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | K0 | +111.53% | 0.9167 | 1.2705 | -22.68% | -1.690% | 68.94 | 45.06 bps | 204 | 57.25% |
| BTC-USDT | K1 | 0.00% | 0.0000 | undefined | 0.00% | 0.000% | 0.00 | undefined | 0 | 0.00% |
| ETH-USDT | K0 | +67.94% | 0.6171 | 0.4048 | -47.30% | -2.183% | 47.31 | 57.86 bps | 140 | 49.70% |
| ETH-USDT | K1 | 0.00% | 0.0000 | undefined | 0.00% | 0.000% | 0.00 | undefined | 0 | 0.00% |

K1 had zero profitable folds and zero profitable years in both markets. It had no executable turnover, so edge per turnover is undefined rather than zero.

## Failure mechanism

The unconstrained fractions were not themselves zero:

```text
BTC mean / median quarter Kelly     23.04% / 29.36%
ETH mean / median quarter Kelly     13.62% / 13.73%

BTC base-long hours with k_t > 0    11,016
ETH base-long hours with k_t > 0    10,136
```

However, the exact one-hour utility never justified paying the entry cost:

```text
BTC best entry utility gain         -0.0206 bps
BTC median entry utility gain       -1.5662 bps
ETH best entry utility gain         -0.00186 bps
ETH median entry utility gain       -0.9229 bps
positive utility-gain decisions     0 in both markets
```

Thus the family deterministically remained cash. This is not a tail-risk improvement: it is a horizon mismatch. The estimated one-hour conditional log-growth benefit is smaller than the immediate 5 bps one-way adjustment cost even after reducing exposure to quarter Kelly.

Relative to K0, K1 removed annualized gross arithmetic return of 34.51 percentage points in BTC and 29.74 percentage points in ETH, while saving only 3.45 and 2.37 percentage points of modeled annualized fee contribution respectively.

## Regime and tail diagnostics

K1 was cash in both causal volatility regimes, so every K1 regime return, Sharpe, tail loss and turnover metric was zero and edge per turnover remained undefined. This fails the strategy gate despite mechanically eliminating drawdown.

The unchanged baseline remained positive in both regimes:

| Market | Regime | Occupancy | Baseline Sharpe | Baseline edge/turnover |
|---|---|---:|---:|---:|
| BTC | Expansion | 40.89% | 0.962 | 56.80 bps |
| BTC | Compression | 59.11% | 0.898 | 37.17 bps |
| ETH | Expansion | 39.30% | 0.391 | 39.95 bps |
| ETH | Compression | 60.70% | 0.826 | 70.90 bps |

## Statistical evidence

Inference used 5,000 paired, non-circular 168H moving-block resamples within each frozen fold, preserving each fold-boundary row once, seed `20260728`.

```text
Worst-market Sharpe delta       -0.916657
Basic 95% interval              [-1.916202, +0.078476]
One-sided 95% lower bound       -1.743628
Holm-adjusted p                 1.0000
```

The edge-per-turnover endpoint was unavailable because K1 turnover was zero in both markets. The first implementation emitted non-finite JSON for that endpoint. It was repaired to mark the endpoint explicitly undefined and fail closed; the unchanged strategy was then rerun twice with byte-identical output.

DSR was not calculated because the repository-wide independent family inventory is incomplete. PBO was not calculated because one fixed sizing candidate does not provide a valid candidate-by-split CSCV matrix.

## Capacity diagnostics

K1 places no position, so its adjusted notional and modeled fee are zero at USD 10,000, USD 100,000 and USD 1,000,000. This is not capacity evidence; it is another consequence of the no-trade failure.

For reference, unchanged K0 at USD 1,000,000 implies:

```text
BTC annual adjusted notional    $68.94M
BTC modeled annual fee          $34,472
BTC maximum one-hour adjustment $1.00M

ETH annual adjusted notional    $47.31M
ETH modeled annual fee          $23,657
ETH maximum one-hour adjustment $1.00M
```

Spread, depth, impact, latency, partial fill and adverse selection were not measured.

## Causal checks

- Exact ZIP and internal manifest reconstruction: PASS.
- Confirmed unique contiguous 1H grid: PASS.
- Canonical next-open benchmark parity: exact for return, Sharpe and turnover.
- Future-suffix mutation: zero prefix error for base position, K1 position, posterior mean, predictive variance and Kelly fraction.
- Fold-boundary position continuity: PASS.
- Two complete reruns: byte-identical.

## Verdict

```text
rejected_exact_family_cooldown
```

The exact family—expanding long-state return estimator, predictive variance `s²(1+1/n)`, quarter Kelly, one-hour risk-aversion-4 utility and exact 5 bps fee-aware action comparison—is rejected on the BTC/ETH development evidence.

It must not be rescued on this window by extending the utility horizon, amortizing the fee, changing the Kelly fraction, introducing a minimum holding period, adding a confidence floor, replacing the expanding estimator with a window, or combining it with another overlay. A future sizing experiment must be structurally different and should attach to a new Alpha architecture whose forecast horizon and expected holding duration are explicitly matched before testing.
