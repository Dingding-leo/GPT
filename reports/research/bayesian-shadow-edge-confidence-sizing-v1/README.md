# Bayesian shadow-edge confidence sizing v1

## Verdict

`rejected_exact_family_cooldown`

The candidate improved modeled tail risk and Sharpe in both development markets, but it failed the predeclared cross-market edge-per-turnover and uncertainty gates. BTC net return and edge per turnover deteriorated materially, and neither market produced a positive dependence-aware lower confidence bound for Sharpe or edge improvement.

This is development-only evidence on already-consumed BTC-USDT and ETH-USDT OOS. It does not promote the rejected base strategy or authorize paper/live trading.

## Frozen policy

For the unchanged canonical strategy's completed net returns `r0_net`, at close `t`:

```text
window = previous 720 completed B0 net returns ending at t
z = sqrt(720) * mean(window) / sample_std(window, ddof=1)
confidence = max(0, 2 * NormalCDF(z) - 1)
B1_target[t] = B0_target[t] * confidence
```

The target first earns the next hour's return. Confidence is computed from the immutable B0 shadow path, not recursively from B1. Invalid/incomplete windows map to zero exposure. Exactly one candidate was evaluated; no alternative lookback, prior, transform, floor, threshold, smoothing, or rescue variant was run.

## Immutable evidence

- Workflow run: `30347175588`
- Source head: `d7cc15839755484b682d6e9094298b8a32f70230`
- BTC artifact: `8683465243`, ZIP SHA-256 `e9bdc2cee531f0b71539a6f4c2b306f2ae702e64bbbe8443ec16bf69c558147a`
- ETH artifact: `8683462187`, ZIP SHA-256 `1f865024ae9d3ce7aa51bfe72bbab054b0377eef01780c75f60f6e8aa2cdc51e`
- Sample: 25,920 OOS 1H observations per market, 12 × 2,160H folds
- Period: 2023-07-24 00:00 UTC through 2026-07-07 23:00 UTC
- Fee: exactly 5 bps one-way on absolute position change
- New OOS consumed: false
- Untouched markets consumed: zero

Both ZIP digests and all 13 internal manifest files per artifact were verified. Canonical targets, turnover, fees, and hourly returns reconstructed within `1e-11`; simple-trend hourly benchmark parity was within `1.11e-16`. Future-suffix mutation left all earlier confidence states unchanged, and two full executions were byte-identical.

## Aggregate metrics

| Market | Policy | Net return | Sharpe | Calmar | Max drawdown | ES 1% | Annual turnover | Edge/turnover | Adjustments | Mean interval | Time in market |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC | B0 | 43.59% | 0.637 | 0.485 | -26.84% | -1.250% | 45.23 | 33.18 bps | 15,991 | 1.62H | 61.23% |
| BTC | B1 | 30.13% | 0.708 | 0.559 | -16.65% | -0.792% | 43.63 | 22.63 bps | 8,567 | 3.03H | 32.17% |
| ETH | B0 | 16.31% | 0.342 | 0.180 | -29.03% | -1.172% | 62.38 | 12.05 bps | 14,413 | 1.80H | 54.96% |
| ETH | B1 | 24.58% | 0.606 | 0.502 | -15.37% | -0.804% | 34.64 | 24.20 bps | 7,713 | 3.36H | 29.09% |

The confidence multiplier was zero for 60.32% of BTC hours and 64.46% of ETH hours; median confidence was zero in both markets.

### Tail behavior

```text
BTC worst 24H:   -12.87% -> -8.55%
BTC worst 168H:  -21.09% -> -11.77%
ETH worst 24H:    -9.83% -> -4.64%
ETH worst 168H:  -16.60% -> -11.36%
```

### Breadth and concentration

```text
BTC profitable folds:   4/12 -> 6/12
BTC profitable years:   3/4  -> 2/4
BTC positive-fold concentration: 59.55% -> 72.75%

ETH profitable folds:   5/12 -> 5/12
ETH profitable years:   1/4  -> 1/4
ETH positive-fold concentration: 37.40% -> 47.43%
```

The sizing rule therefore improved BTC fold count while making gains more concentrated and losing one profitable calendar year. ETH breadth did not improve.

## Benchmark and regime evidence

Residual Sharpe versus the canonical 2,160H simple-trend benchmark remained negative:

```text
BTC: -0.8180 -> -0.7792
ETH: -0.5867 -> -0.4828
```

Volatility-regime transfer was not stable. BTC Sharpe improved in the lowest, second, and highest causal volatility quartiles but fell from `1.469` to `0.388` in Q3. ETH Sharpe improved in Q1 and Q3 but deteriorated in Q2 and Q4. The candidate did not establish a market-consistent conditional risk-premium relationship.

## Uncertainty

5,000 paired non-circular 168H moving-block resamples were drawn within each fold with seed `20260728`; each fold-boundary row was retained exactly once. Four one-sided endpoints were Holm-adjusted.

| Market | Endpoint | Observed B1-B0 | One-sided 95% lower bound | Holm-adjusted p |
|---|---|---:|---:|---:|
| BTC | Sharpe | +0.0714 | -0.6104 | 1.0000 |
| BTC | Edge/turnover | -10.55 bps | -45.17 bps | 1.0000 |
| ETH | Sharpe | +0.2639 | -0.4182 | 1.0000 |
| ETH | Edge/turnover | +12.16 bps | -18.21 bps | 1.0000 |

No DSR or PBO was calculated because the repository does not contain a complete deduplicated independent-family inventory or the required candidate-by-split matrix.

## Fee and capacity diagnostics

Cumulative modeled fee burden fell from `0.06691` to `0.06454` return units for BTC and from `0.09229` to `0.05125` for ETH. At a transparent USD 10,000 reference notional (the repository does not declare an intended notional):

```text
BTC annual adjusted notional:  $436,266
BTC modeled annual fee:        $218
BTC max one-hour adjustment:   $3,049

ETH annual adjusted notional:  $346,382
ETH modeled annual fee:        $173
ETH max one-hour adjustment:   $4,004
```

At USD 1,000,000, annual adjusted notional is approximately USD 43.63M for BTC and USD 34.64M for ETH; maximum one-hour adjustments are approximately USD 304,934 and USD 400,401. Spread, depth, impact, latency, no-fill, partial-fill, and adverse-selection effects were not measured, so this is not a scaling authorization.

## Methodological repair

The first diagnostic draft compounded non-contiguous volatility-regime observations and reported regime total return/max drawdown as if each regime were one continuous path. Those statistics were invalid. They were removed, and the full experiment was rerun; regime evidence now contains only conditional occupancy, arithmetic mean, Sharpe, expected shortfall, turnover, and edge per turnover.

## Decision

Reject the exact family. The candidate is too aggressive: it holds zero confidence for most hours, reduces BTC gross opportunity enough to lose 13.46 percentage points of net return, and does not produce adjusted cross-market evidence of incremental edge per turnover. The exact `720H / B0 net-return / flat-prior Normal sign confidence / multiplicative hourly sizing / zero fail-closed` signature enters cooldown on this BTC/ETH development window.

The next non-duplicative sizing experiment should use an auditable training-only selector-candidate disagreement matrix after a genuinely new base architecture exists. It must not retune this policy on the consumed BTC/ETH evidence.
