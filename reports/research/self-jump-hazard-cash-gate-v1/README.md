# Self-jump hazard cash gate v1 — rejected

## Frozen hypothesis

A target instrument’s own negative liquidity-stress jumps may cluster. The candidate applies a one-hour cash gate to the unchanged 2,160H simple-trend target only when the current completed hour is a negative jump, quote volume is above its prior 720H median, and the causal Jeffreys-posterior transition hazard satisfies `p11 > p01`.

No alternative quantile, lookback, volume rule, prior, hold time, threshold, partial sizing, smoothing, or rescue variant was evaluated.

## Data and timing

- Immutable confirmed OKX 1H BTC-USDT and ETH-USDT artifacts from workflow `30347175588`.
- Artifact IDs: BTC `8685574446`; ETH `8685572234`.
- Evaluation: `2023-07-24T00:00:00Z` through `2026-07-07T23:00:00Z`, 25,920 hours and 12 × 2,160H folds per market.
- Fields: `timestamp, open, high, low, close, volume_quote_alt, confirm`.
- All feature references exclude the current hour; target is formed after confirmed close and applied at the next observed hourly open.
- Fee: exactly 5 bps one-way on absolute position changes.

## Results

| Market | Policy | Net return | Sharpe | Max DD | Turnover | Edge/turnover | Profitable folds |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | J0 | 111.53% | 0.917 | -22.68% | 68.94 | 45.06 bps | 5/12 |
| BTC-USDT | J1 | 32.59% | 0.455 | -29.70% | 325.80 | 4.57 bps | 4/12 |
| ETH-USDT | J0 | 67.94% | 0.617 | -47.30% | 47.31 | 57.86 bps | 6/12 |
| ETH-USDT | J1 | 13.25% | 0.313 | -52.31% | 260.91 | 5.15 bps | 6/12 |

### BTC-USDT

- Negative-jump/gate decisions: `745`; actually removed baseline exposure for `423` hours (`1.63%`).
- Mean next-open return during removed exposure: `0.023369%` per hour, versus `0.006399%` during other baseline-long hours.
- Gross annualized-mean delta: `-3.3407%`; fee contribution: `-12.8426%`; net delta: `-16.1833%`.
- J1−J0 residual Sharpe: `-1.809`.

### ETH-USDT

- Negative-jump/gate decisions: `754`; actually removed baseline exposure for `347` hours (`1.34%`).
- Mean next-open return during removed exposure: `0.027852%` per hour, versus `0.006249%` during other baseline-long hours.
- Gross annualized-mean delta: `-3.2663%`; fee contribution: `-10.6796%`; net delta: `-13.9459%`.
- J1−J0 residual Sharpe: `-1.243`.

## Adjusted uncertainty

Paired 5,000-resample, non-circular 168H moving blocks were sampled within each fold, retaining every fold boundary row exactly once. Four endpoints were Holm-adjusted.

| Endpoint | Observed | One-sided 95% lower | Holm p |
|---|---:|---:|---:|
| BTC-USDT_edge_delta_bps | -40.4914 bps | -79.7444 bps | 1.0000 |
| BTC-USDT_sharpe_delta | -0.4616 | -0.6883 | 1.0000 |
| ETH-USDT_edge_delta_bps | -52.7087 bps | -123.0229 bps | 1.0000 |
| ETH-USDT_sharpe_delta | -0.3043 | -0.5323 | 1.0000 |

## Failure mechanism

The causal posterior did identify jump clustering (`p11 > p01`), but the excluded next-hour returns were positive in both markets. The candidate therefore removed rebound exposure while generating two extra position transitions around many events. Both gross edge and fee efficiency deteriorated; BTC and ETH Sharpe fell materially, and drawdown worsened.

## Methodological repair

An unpublished first run compounded hourly `J1−J0` return differences as though that difference series were a tradable residual path. That quantity was removed. The unchanged policies and bootstrap were rerun with an explicit gross-versus-fee decomposition; two complete executions produced byte-identical JSON.

## Verdict

```text
rejected_exact_family_cooldown
```

The exact `1% prior-24H bipower negative jump / current volume above prior-720H median / Jeffreys p11>p01 / one-hour cash` family must not be rescued on the same BTC/ETH development evidence by changing its quantile, lookbacks, volume condition, prior, hold duration, sizing, or combining it with another overlay.

The next non-duplicative liquidity experiment should use prospectively captured public spread, depth, and individual-trade resilience rather than another OHLCV cash gate.
