# Worst-decile exposure timing diagnostic

## Hypothesis

For both BTC-USDT and ETH-USDT, the strategy's mean **executed** out-of-sample position is lower on the asset's worst-decile return days than on all other days. The joint hypothesis passes only if the 95% paired moving-block-bootstrap lower bound for

```text
mean position on non-tail days - mean position on tail days
```

is positive in both development markets.

Canonical signature:

```text
worst-decile-exposure-timing-v1|markets=BTC-USDT,ETH-USDT|tail=asset-return-bottom-decile-recomputed-per-resample|metric=mean-position-nontail-minus-tail|position=persisted-executed-oos|block=20|resamples=2000|confidence=0.95|seeds=BTC-USDT:20260722,ETH-USDT:20260723|candidate_count=1
```

## Economic rationale

A long/cash risk-control strategy can show lower losses merely because its average exposure is low. A stronger timing mechanism would already hold less exposure before the market's most severe sessions. The persisted `position` column is the one-bar-lagged executed position, so same-day tail labels cannot change the position being audited.

This is a post-event mechanism diagnostic, not a tradable signal. BTC-USDT and ETH-USDT remain development markets.

## Fixed specification

- Provider: OKX spot.
- Markets: BTC-USDT and ETH-USDT.
- Bar: `1Dutc`.
- OOS observations: 2,340 per market, January 11, 2020 through June 7, 2026 UTC.
- Tail: bottom 10% of persisted asset returns; the threshold is recomputed inside every resample.
- Primary metric: non-tail mean executed position minus tail mean executed position.
- Resampling: paired 20-day moving blocks without circular wrapping.
- Resamples: 2,000 per market.
- Confidence: 95% percentile interval.
- Seeds: `20260722` for BTC-USDT and `20260723` for ETH-USDT.
- Candidates searched: exactly one metric, tail definition, block length, confidence level, and seed rule.

No alternative percentile, position definition, market subgroup, benchmark, strategy parameter, fee, execution delay, split, or holdout rule was searched after observing the result.

## Results

| Market | Tail threshold | Tail mean position | Non-tail mean position | Exposure delta | 95% interval | P(delta > 0) |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | -3.1179% | 24.9768% | 27.6487% | +2.6719 pp | [-2.1677, +7.7884] pp | 85.00% |
| ETH-USDT | -4.2113% | 20.6330% | 21.8255% | +1.1925 pp | [-3.0632, +4.6318] pp | 67.75% |

## Verdict: rejected

Both point estimates have the expected sign, but both 95% lower bounds are negative. The data therefore do not establish that the strategy reliably reduced exposure before worst-decile market sessions. Existing lower-drawdown or severe-day-loss evidence must not be promoted into a statistically supported pre-positioning claim.

## Provenance

- Source workflow run: `29874768418`.
- Source artifact: `8512566174` (`quant-research-354`).
- Source artifact SHA-256: `288c19af640e03f8b69e20edd61002c04a7e007ee1973cab287224a0a687b15f`.
- Tested merge commit: `5fdcffbd0b3ba38c0d25b5502807fb1814202b8d`.
- Persistent source head: `df8dd830d10f225c27edae41cccda0ae3592939e`.
- Source base: `60251e9d945be29645aca86d4133e18ae9a90652`.
- BTC returns SHA-256: `539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73`.
- ETH returns SHA-256: `027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6`.

`result.json` is generated deterministically by `analysis.py` from the verified artifact.

## Limitations

The bottom-decile threshold is sample-relative, and the diagnostic measures association rather than causality. It does not model intraday gaps, order-book liquidity, spread, impact, capacity, or partial fills. A non-rejection would still not prove deployable crash prediction.
