# Weekday/Weekend Conditional-Mean Consistency

Verdict: **reject**

## Hypothesis

For both BTC-USDT and ETH-USDT, net rolling OOS returns have a positive conditional annualized arithmetic mean in weekday and weekend sessions, with every 95% moving-block-bootstrap lower bound above zero.

## Economic rationale

Crypto liquidity and institutional participation differ between weekdays and weekends. A robust daily strategy should not depend on only one calendar-liquidity regime.

## Predeclared specification

- One candidate only.
- UTC Monday-Friday are weekdays; UTC Saturday-Sunday are weekends.
- Conditional daily arithmetic means are multiplied by 365.
- Timestamp/return pairs are resampled with non-circular 20-day moving blocks.
- 2,000 resamples, 95% confidence, deterministic market-specific seeds.

## Results

| Market | Regime | Observations | Annualized mean | 95% interval | P(mean > 0) | Pass |
|---|---|---:|---:|---:|---:|---|
| BTC-USDT | weekday | 1670 | 16.976468% | -7.315263% to 46.355948% | 91.70% | false |
| BTC-USDT | weekend | 670 | 17.648742% | -3.153859% to 40.706746% | 94.70% | false |
| ETH-USDT | weekday | 1670 | 8.219656% | -14.599383% to 32.440190% | 75.80% | false |
| ETH-USDT | weekend | 670 | 27.374265% | 0.377018% to 57.576947% | 97.60% | true |

## Verdict

The joint hypothesis is rejected. ETH-USDT weekends passed, but BTC-USDT weekdays, BTC-USDT weekends, and ETH-USDT weekdays had non-positive 95% lower bounds. No strategy improvement is claimed.

## Provenance

- Provider: OKX spot, `1Dutc`.
- Markets: BTC-USDT and ETH-USDT.
- 2,340 persisted net rolling OOS observations per market, 2020-01-11 through 2026-06-07 UTC.
- Source workflow: `29891907836`.
- Source artifact: `8518541653` (`quant-research-source-608`).
- Artifact SHA-256: `049c82dff0ed05c37e106d8ac30857532d5f20f18cc9191aaf6f100d3642b7c0`.

## Limitations

- BTC-USDT and ETH-USDT are development markets, not untouched holdouts.
- Conditional regime means are descriptive and do not constitute a trading calendar rule.
- The analysis does not model spread, impact, capacity, latency, or partial fills.
