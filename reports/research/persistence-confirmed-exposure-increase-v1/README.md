# Persistence-confirmed exposure increases v1

## Verdict

`rejected_exact_family_cooldown`

The candidate improved every deterministic point estimate in BTC-USDT and ETH-USDT, but the predeclared cross-market uncertainty gate failed: ETH's Holm-adjusted one-sided lower bounds for annualized-mean and Sharpe improvement remained below zero. The exact family is rejected and may not be rescued on the same development window.

## Frozen policy

`P0` is the unchanged canonical causal position path. `P1` executes reductions immediately, but increases exposure only after two consecutive completed-hour canonical intents remain above the committed position. The executed increase is the lower of the two intents.

```text
if q_t < c_(t-1):
    c_t = q_t
elif q_t > c_(t-1) and q_(t-1) > c_(t-1):
    c_t = min(q_t, q_(t-1))
else:
    c_t = c_(t-1)
```

The first OOS position and fee are preserved from the canonical artifact. State carries across all selector-fold boundaries. Equality is no-trade. No threshold, lookback, smoothing, timeout, tolerance, or rescue variant was evaluated.

## Data and reconstruction

- Public immutable workflow: `30347175588`.
- BTC artifact: `8685574446`, ZIP SHA-256 `d36b151d0279e552f0f561403647ca8495febf6bd7c87c0b85cf0e7ad3df6119`.
- ETH artifact: `8685572234`, ZIP SHA-256 `e32884abe83663b36bc52ce4f4b3cc60b03bb2f4f2948853134dc6831706a9bb`.
- `25,920` OOS confirmed 1H rows per market.
- `12 × 2,160H` folds.
- `2023-07-24 00:00 UTC` through `2026-07-07 23:00 UTC`.
- Exactly `5 bps` one-way on absolute turnover.

All 13 payload files in each artifact passed the published SHA-256 manifest. Baseline gross, fee, and net-return reconstruction errors were below `3.2e-16`. Real-path future-suffix mutation left every earlier P1 position unchanged, and two complete P1 replays were byte-identical.

## Results

| Market | Metric | P0 | P1 |
|---|---:|---:|---:|
| BTC | Net return | 43.59% | 46.13% |
| BTC | Sharpe | 0.637 | 0.664 |
| BTC | Calmar | 0.485 | 0.511 |
| BTC | Max drawdown | -26.84% | -26.76% |
| BTC | Annual turnover | 45.23 | 31.99 |
| BTC | Edge / turnover | 33.18 bps | 48.69 bps |
| BTC | Adjustments | 15,991 | 11,782 |
| BTC | Mean hours between adjustments | 1.58 | 2.14 |
| BTC | No-trade frequency | 38.31% | 54.54% |
| ETH | Net return | 16.31% | 18.15% |
| ETH | Sharpe | 0.342 | 0.368 |
| ETH | Calmar | 0.180 | 0.206 |
| ETH | Max drawdown | -29.03% | -28.19% |
| ETH | Annual turnover | 62.38 | 43.94 |
| ETH | Edge / turnover | 12.05 bps | 18.19 bps |
| ETH | Adjustments | 14,413 | 10,550 |
| ETH | Mean hours between adjustments | 1.80 | 2.46 |
| ETH | No-trade frequency | 44.39% | 59.30% |

Fold breadth did not improve: BTC remained `4/12` profitable folds and ETH remained `5/12`. Residual Sharpe versus simple trend remained negative:

```text
BTC  -0.8180 -> -0.7865
ETH  -0.5867 -> -0.5715
```

Tail changes were small rather than strategy-defining:

```text
BTC ES 1%       -1.2503% -> -1.2466%
BTC worst 24H  -12.8674% -> -12.8392%
BTC worst 168H -21.0904% -> -21.0678%

ETH ES 1%       -1.1721% -> -1.1643%
ETH worst 24H   -9.8338% -> -9.7681%
ETH worst 168H -16.6010% -> -16.5462%
```

## Realized-edge attribution

The candidate did not improve gross predictive return. Its point-estimate net benefit came entirely from lower modeled fees:

```text
BTC gross annualized-mean change   -0.0901 percentage points
BTC fee-saving contribution        +0.6619 percentage points
BTC net annualized-mean change      +0.5717 percentage points

ETH gross annualized-mean change   -0.4447 percentage points
ETH fee-saving contribution        +0.9222 percentage points
ETH net annualized-mean change      +0.4775 percentage points
```

P1 suppressed `4,168` BTC and `3,817` ETH exposure increases. Annual modeled fee burden fell from `2.261%` to `1.599%` for BTC and from `3.119%` to `2.197%` for ETH.

## Confirmatory uncertainty

Paired bootstrap contract:

- `5,000` resamples;
- `168H` non-circular blocks within each fold;
- each fold boundary row retained exactly once;
- identical indices across markets and policies;
- seed `20260728`;
- Holm correction across BTC/ETH annualized-mean and Sharpe improvements.

```text
BTC annualized-mean delta   +0.5717 pp
one-sided 95% lower bound   +0.2649 pp
Holm-adjusted p              0.00160

BTC Sharpe delta             +0.02668
one-sided 95% lower bound    +0.01336
Holm-adjusted p              0.00160

ETH annualized-mean delta    +0.4775 pp
one-sided 95% lower bound    -0.2328 pp
Holm-adjusted p              0.17836

ETH Sharpe delta             +0.02570
one-sided 95% lower bound    -0.00591
Holm-adjusted p              0.17836
```

BTC passed every deterministic and uncertainty gate. ETH passed every deterministic gate but failed both confirmatory lower-bound gates, so the family fails closed.

## Reporting repair made before publication

The first result payload exposed cumulative gross return and fees but did not provide an exact arithmetic gross-versus-fee decomposition. Because the mechanism's claim is realized edge, that omission could mischaracterize fee savings as predictive alpha. Before publication, the artifact and reproducer were repaired to persist gross annualized mean, annualized fee saving, net annualized-mean change, and their reconstruction error. The full experiment was rerun unchanged; the verdict did not change.

## Execution limits

Spread, slippage, market impact, queue position, fill probability, partial fills, additional latency, and adverse selection were not measured. Touch was not assumed to equal fill. Since the candidate fails the canonical 5 bps development gate, these unmeasured frictions can only weaken the case.

## Cooldown

Do not rescue this exact family on the same BTC/ETH window by changing confirmation duration, adding a tolerance band, delaying reductions, changing the `min` coalescing rule, combining it with H1, or adding thresholds.

The next non-duplicative realized-edge experiment should wait for a materially orthogonal causal alpha architecture and use training-derived forecast disagreement or uncertainty in the trade/no-trade utility. It should not apply another deterministic transformation to the rejected S0 target path.
