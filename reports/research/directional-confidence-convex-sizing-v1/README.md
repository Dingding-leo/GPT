# Directional-confidence convex sizing v1

## Verdict

`rejected_exact_family_cooldown`

The candidate reduced drawdown, expected shortfall, exposure, turnover, and modeled fees, but it also reduced net return, Sharpe, Calmar, edge per turnover, and benchmark-relative performance. ETH profitable-fold breadth fell from 5/12 to 3/12. The exact convex sizing family must not be rescued on the same BTC/ETH development window.

## Frozen policy

The canonical target is reconstructed as

```text
d_t = max(0, tanh(w * trend_score_t + (1 - w) * reversal_score_t))
q_t = d_t * volatility_scalar_t
```

where the momentum lookback, reversal lookback, and trend weight are the exact fold-selected canonical values. The only new candidate is

```text
q_C1,t = q_t * d_t = d_t^2 * volatility_scalar_t
```

No exponent, threshold, window, floor, smoothing, hysteresis, minimum trade, drawdown override, or combination with H1 was searched.

## Immutable inputs

- Workflow: `30347175588`
- Source head: `d7cc15839755484b682d6e9094298b8a32f70230`
- BTC artifact: `8683465243`
- BTC ZIP SHA-256: `e9bdc2cee531f0b71539a6f4c2b306f2ae702e64bbbe8443ec16bf69c558147a`
- ETH artifact: `8683462187`
- ETH ZIP SHA-256: `1f865024ae9d3ce7aa51bfe72bbab054b0377eef01780c75f60f6e8aa2cdc51e`
- Per market: 43,929 confirmed real OKX 1H bars and 25,920 canonical OOS rows
- OOS interval: 2023-07-24 00:00 UTC through 2026-07-07 23:00 UTC
- Folds: 12 × 2,160 hours per market
- Fee: exactly 5 bps one way on absolute position adjustment

All 13 files in each downloaded artifact were checked against `artifact-manifest.sha256`. Canonical target, position, and net-return reconstruction errors were below `1e-11`.

## Results

| Market | Policy | Net return | Sharpe | Calmar | Max drawdown | ES 1% | Annual turnover | Edge/turnover | Profitable folds |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC | C0 | 43.59% | 0.637 | 0.485 | -26.84% | -1.250% | 45.23 | 33.18 bps | 4/12 |
| BTC | C1 | 34.17% | 0.606 | 0.444 | -23.54% | -1.067% | 39.21 | 30.21 bps | 5/12 |
| ETH | C0 | 16.31% | 0.342 | 0.180 | -29.03% | -1.172% | 62.38 | 12.05 bps | 5/12 |
| ETH | C1 | 5.67% | 0.195 | 0.079 | -23.72% | -0.931% | 45.21 | 7.17 bps | 3/12 |

Additional tail results:

```text
BTC worst 24H:  -12.87% -> -9.32%
BTC worst 168H: -21.09% -> -15.95%
ETH worst 24H:   -9.83% -> -6.72%
ETH worst 168H: -16.60% -> -12.36%
```

The candidate did not reduce adjustment count because it changed the magnitude of every nonzero canonical revision rather than suppressing decisions. It reduced annualized turnover by 6.02 in BTC and 17.17 in ETH, but the gross return sacrificed by down-weighting moderate-confidence forecasts exceeded the fee saving.

Benchmark-residual Sharpe versus the identical simple-trend benchmark deteriorated:

```text
BTC: -0.8180 -> -0.8787
ETH: -0.5867 -> -0.6616
```

## Confidence-regime diagnosis

Only the highest directional-confidence regime, `d_t >= 0.75`, had positive net hourly strategy mean and positive Sharpe in both markets. Lower regimes were weak or negative after fees. However, the parameter-free convex map reduced all sub-unit signals continuously rather than selectively avoiding only the economically negative regimes. On the frozen development sample this improved tail risk but removed too much profitable exposure, especially in ETH during 2024 and 2025.

This diagnosis cannot be used to add a `0.75` threshold on the same development window; that would be post-result threshold selection and a new family.

## Statistical gate

Paired bootstrap contract:

- 5,000 resamples
- 168-hour non-circular moving blocks
- resampling within each fold
- each fold boundary row retained exactly once
- identical indices for C0 and C1
- seed `20260728`
- Holm adjustment across BTC/ETH Sharpe and edge-per-turnover endpoints

| Market | Endpoint | Observed C1-C0 | Basic 95% interval | One-sided lower bound | Holm p |
|---|---|---:|---:|---:|---:|
| BTC | Sharpe | -0.0308 | [-0.2562, 0.1757] | -0.2258 | 1.0 |
| BTC | Edge/turnover | -2.97 bps | [-14.26, 9.30] bps | -12.63 bps | 1.0 |
| ETH | Sharpe | -0.1472 | [-0.4353, 0.0905] | -0.3908 | 1.0 |
| ETH | Edge/turnover | -4.88 bps | [-15.53, 4.04] bps | -14.03 bps | 1.0 |

No confirmatory endpoint passed.

## Capacity diagnostics

These values include only modeled turnover and the exact 5 bps exchange fee; spread, depth, impact, latency, and fill risk remain unmeasured.

For C1 at USD 1,000,000 notional:

```text
BTC annual adjusted notional: $39.21M
BTC modeled annual fee:       $19,604
BTC max one-hour adjustment:  $679,802

ETH annual adjusted notional: $45.21M
ETH modeled annual fee:       $22,606
ETH max one-hour adjustment:  $445,064
```

The family is rejected before any capacity promotion decision. The USD 1,000,000 diagnostics therefore serve only as a scaling warning, not as a limited-capital rejection reason.

## Validation and repaired defect

A future-suffix mutation changed 21,408 later price rows in each market. Directional confidence, canonical target, and C1 target were byte-identical through the cutoff, while later outputs changed.

The first result artifact included a wall-clock generation timestamp, so two otherwise identical runs were not byte-identical. This was repaired before publication by replacing the runtime timestamp with the immutable issue predeclaration timestamp. Two full executions then produced identical JSON bytes and identical SHA-256.

- Result payload SHA-256: `ef7b9f2ea5a282b19a76a78d2cc16236d57f811af25dcad8c684b9e7d7658a3c`
- Result file SHA-256: `ccab5277f9a99e4feae2308347e96f08af9555d60e3c0f03bc1e44b194029369`
- Causal-validation payload SHA-256: `6b06dc01921198e3094fa60706a91572479236e617b9b36cbcb1f05bd709b2bf`

## Cooldown signature

The following exact family is closed on this BTC/ETH window:

```text
canonical target multiplied by its reconstructed directional signal
quadratic directional-confidence map
d_t^2 * volatility_scalar_t
no threshold or hysteresis
same canonical selector and folds
```

Do not rescue it by changing the exponent, adding a confidence cutoff, combining it with H1, adding a floor, or selecting a regime after seeing these results.

The next distinct sizing hypothesis should estimate forecast uncertainty from training-only candidate dispersion or selector-policy disagreement after #545 produces the complete 27-candidate evidence table. That would use model uncertainty rather than another deterministic transformation of the current S0 target magnitude.
