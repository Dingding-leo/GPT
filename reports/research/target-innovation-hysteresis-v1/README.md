# Target-Innovation Hysteresis v1

## Verdict

`retain_as_development_only_turnover_overlay_after_robustness_repair`

The one predeclared candidate in issue #542 passes every frozen H1-versus-H0 acceptance condition on both BTC-USDT and ETH-USDT. It materially reduces unnecessary position revisions while improving net return, Sharpe, Calmar, and deterministic edge per turnover under the unchanged 5 bps one-way fee.

This is **not** a promotion verdict for the base Alpha architecture. BTC still has only 4/12 profitable folds and 59.08% of positive fold return in its largest fold; both markets retain negative residual Sharpe versus the canonical simple-trend benchmark.

## Frozen policy

- H0: unchanged canonical fold-local target.
- H1: use the prior 168 completed canonical target innovations, excluding the current innovation.
- `sigma_t = 1.4826 * median(|dq - median(dq)|)`.
- `band_t = 1.645 * sigma_t`.
- Commit `q_t` only when `abs(q_t - committed) > band_t`; equality is no-trade.
- Incomplete or non-finite history falls back to the unchanged canonical target.
- State and position carry across fold boundaries.
- Decision at close `t` first affects the next 1H return.
- Fee remains exactly 5 bps one-way on absolute position adjustment.

No alternate lookback, multiplier, smoothing, minimum adjustment, partial sizing, cash override, or rescue variant was evaluated.

## Immutable development evidence

Workflow run: `30347175588`

Head: `d7cc15839755484b682d6e9094298b8a32f70230`

| Market | Artifact ZIP SHA-256 | Returns CSV SHA-256 | OOS rows | Period |
|---|---|---|---:|---|
| BTC-USDT | `e9bdc2cee531f0b71539a6f4c2b306f2ae702e64bbbe8443ec16bf69c558147a` | `72b34a405914057a71d6d47fa60251a591060d9d5220c717fbcf179b7073f1a6` | 25,920 | 2023-07-24 00:00 UTC to 2026-07-07 23:00 UTC |
| ETH-USDT | `1f865024ae9d3ce7aa51bfe72bbab054b0377eef01780c75f60f6e8aa2cdc51e` | `e243fc10586536d83a416d6241ad8b3061d5bb0bb5b2493a1a23e539fcba9d1d` | 25,920 | 2023-07-24 00:00 UTC to 2026-07-07 23:00 UTC |

Independent reconstruction matches the canonical target, position, and hourly strategy return within `3.89e-15`, `3.89e-15`, and `1.11e-16`, respectively.

## Strategy metrics

### BTC-USDT

| Metric | H0 | H1 | Change |
|---|---:|---:|---:|
| Net total return | 43.5898% | 46.3684% | +2.7786 pp |
| Sharpe | 0.6369 | 0.6645 | +0.0276 |
| CAGR | 13.0061% | 13.7405% | +0.7344 pp |
| Calmar | 0.4845 | 0.5122 | +0.0277 |
| Max drawdown | -26.8428% | -26.8256% | +0.0172 pp |
| Annualized turnover | 45.2257 | 30.6472 | -32.24% |
| Exchange-fee sum | 6.6909% | 4.5341% | -2.1568 pp |
| Net edge / turnover | 33.18 bps | 51.07 bps | +17.89 bps |
| Adjustment count | 15,991 | 4,549 | -71.55% |
| Mean hours between adjustments | 1.58 | 5.55 | +3.98 h |
| Target decisions suppressed | — | 82.99% | — |
| Profitable folds | 4/12 | 4/12 | unchanged |

### ETH-USDT

| Metric | H0 | H1 | Change |
|---|---:|---:|---:|
| Net total return | 16.3126% | 21.1196% | +4.8069 pp |
| Sharpe | 0.3425 | 0.4048 | +0.0623 |
| CAGR | 5.2397% | 6.6899% | +1.4503 pp |
| Calmar | 0.1805 | 0.2364 | +0.0559 |
| Max drawdown | -29.0291% | -28.2962% | +0.7329 pp |
| Annualized turnover | 62.3810 | 45.6966 | -26.75% |
| Exchange-fee sum | 9.2290% | 6.7606% | -2.4684 pp |
| Net edge / turnover | 12.05 bps | 19.44 bps | +7.40 bps |
| Adjustment count | 14,413 | 4,842 | -66.40% |
| Mean hours between adjustments | 1.80 | 5.35 | +3.56 h |
| Target decisions suppressed | — | 81.85% | — |
| Profitable folds | 5/12 | 5/12 | unchanged |

## Robustness repair and attacks

The original bootstrap sampled every fold row as if it were exchangeable. That allowed a fold-boundary row, which contains a path-specific carried-position fee, to be sampled zero or multiple times. The repaired bootstrap keeps the first row of every fold exactly once and resamples only the remaining rows using paired 168-hour non-circular blocks. It also reports centered-bootstrap probabilities and basic intervals rather than treating a percentile-bootstrap frequency as a standalone null p-value.

| Market | Endpoint | Observed H1−H0 | Repaired basic 95% interval | One-sided 95% lower bound |
|---|---|---:|---:|---:|
| BTC | Annualized mean | +0.6468% | [+0.3281%, +0.8104%] | +0.3721% |
| BTC | Sharpe | +0.0276 | [+0.0133, +0.0346] | +0.0154 |
| ETH | Annualized mean | +1.3702% | [+0.9197%, +1.7722%] | +0.9919% |
| ETH | Sharpe | +0.0623 | [+0.0409, +0.0814] | +0.0443 |

The centered-bootstrap one-sided probability is `1/5001` for annualized mean and Sharpe in each market. Edge-per-turnover remains unconfirmed: its repaired one-sided lower bound is `-9.79 bps` for BTC and `-8.72 bps` for ETH.

### One-extra-bar execution latency

The same extra 1H delay was applied symmetrically to H0 and H1. H1 still improves:

- BTC total return by `+2.71 pp`, Sharpe by `+0.0269`, and annualized turnover by `-14.57`.
- ETH total return by `+3.09 pp`, Sharpe by `+0.0409`, and annualized turnover by `-16.69`.

### Parameter-neighbourhood stability

The unchanged H1 rule was applied to all four canonical perturbation paths: shorter lookbacks, longer lookbacks, less trend weight, and more trend weight. No H1 parameter was changed. Net return and Sharpe improve for every perturbation in both markets, annualized turnover falls by `14.60–17.56`, and profitable-fold count never decreases.

### Gross-versus-fee decomposition

- BTC gross annualized mean changes by `-0.0821 pp`; the `+0.6468 pp` net improvement is entirely generated by modeled fee savings at exactly 5 bps.
- ETH gross annualized mean changes by `+0.5359 pp`, while modeled fee savings add a further `+0.8342 pp`.

This distinction prevents the BTC result from being described as improved predictive Alpha. It is a turnover-control result under the frozen fee model.

The complete repaired evidence is stored in `robustness.json`.

## Year, regime, and benchmark diagnostics

H1 improves total return in every calendar segment for both markets. It turns ETH 2023 from -0.27% to +0.42%, but it does not make ETH 2024 or 2026 profitable and does not make BTC 2026 profitable.

Diagnostic trailing-168H volatility quartiles were used only for attribution and never for decisions. H1-minus-H0 annualized arithmetic mean is positive in all four volatility regimes for both markets. Tail risk is essentially unchanged; the benefit is fee and revision suppression, not crash protection.

Residual Sharpe versus canonical simple trend improves but remains negative:

- BTC: -0.8180 to -0.7850.
- ETH: -0.5867 to -0.5464.

The overlay should be retained only as a candidate-neutral development-stage target-sizing mechanism for the eventual nominated selector. It does not rescue S0 or authorize paper/live promotion.

## Capacity diagnostics

A normalized intended notional of USD 10,000 is used only for fee/turnover scaling; 10x equals the USD 100,000 rung.

At USD 1,000,000, H1 implies approximately:

- BTC: USD 30.65M annual adjustment notional, USD 15,324 modeled annual exchange fees, USD 746,272 maximum single-hour adjustment.
- ETH: USD 45.70M annual adjustment notional, USD 22,848 modeled annual exchange fees, USD 633,443 maximum single-hour adjustment.

No spread, depth, slippage, impact, fill, latency beyond the explicit one-bar stress, or adverse-selection evidence is included. USD 1M is therefore a scaling blocker pending public liquidity evidence, not a rejection of limited-capital shadow observation.

## Experiment accounting

- New architecture families: 1.
- New candidate policies: 1.
- Development markets: 2.
- New candidate-market evaluations: 2.
- Additional parameter-neighbourhood diagnostics: 8 paired policy-path comparisons.
- Untouched replication consumed: false.
- Prospective shadow evidence consumed: false.
- Original result payload SHA-256: `c4e6fb2f9a23a4b859b72912031b44a71e30a2830c8fa1252b692a77bf15e78a`.
- Robustness payload pre-self-field SHA-256: `6b08d0d7e78f8b0df4e5edd6ce3f9da9ff1ae4305f054cf2c936f3b217c547e4`.
