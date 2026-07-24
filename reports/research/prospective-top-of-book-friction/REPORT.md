# Prospective Top-of-Book Friction

## Hypothesis

A bounded prospective public-OKX collection can obtain twelve valid top-of-book observations for each of BTC-USDT and ETH-USDT with zero unrecovered failures, while both markets satisfy the predeclared spread and transport-timing thresholds.

The fixed thresholds were committed before collection:

- p95 one-way half-spread no greater than 2.5 bps;
- p95 books-request round trip no greater than 1.0 second;
- p95 server-time request round trip no greater than 1.0 second;
- maximum exchange-measured quote age no greater than 1,000 ms;
- maximum absolute midpoint clock skew no greater than 5.0 seconds;
- twelve accepted observations and zero unrecovered failures in both markets.

Exactly one joint evidence candidate was tested. No threshold, market, sample count, retry bound or acceptance rule was changed after viewing the observations.

## Result: rejected

| Market | Accepted / required | Unrecovered failures | Median half-spread | p95 half-spread | p95 books RTT | p95 server RTT | Maximum quote age | Maximum abs. clock skew |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 10 / 12 | 2 | 0.007684 bps | 0.007684 bps | 0.333530 s | 0.325240 s | 300 ms | 0.023294 s |
| ETH-USDT | 11 / 12 | 1 | 0.026686 bps | 0.026695 bps | 0.336228 s | 0.305241 s | 308 ms | 0.025635 s |

Every spread, round-trip, quote-age and clock-skew threshold passed on the accepted observations. The joint candidate nevertheless failed because the producer did not deliver all twelve accepted observations per market:

- BTC sample 6: `ValueError: OKX midpoint clock skew does not match its timestamps`;
- BTC sample 8: the same validation error;
- ETH sample 2: the same validation error.

Candidate accounting:

```text
searched: 1
passed:   0
rejected: 1
```

The observed top-of-book half-spreads are small relative to the fixed 2.5 bps preliminary allowance above the canonical 5 bps one-way exchange fee. This does not establish executable total cost because slippage, nonlinear impact and decision-to-order latency remain unmeasured.

## Provenance

- Provider: public unauthenticated OKX REST endpoints.
- Collection time: July 24, 2026 UTC.
- Workflow run: `30060305841`.
- Workflow artifact: `8584310199`, `prospective-quote-friction-3-attempt-1`.
- Artifact SHA-256: `44e5a388fabb5c9367f83bf259dff9e4a8c09a3691eed17a32530126c626b0c0`.
- Collection branch head: `e9891cd316317469d50108fa74a792d141f02c0d`.
- Tested pull-request merge commit: `188c095a337b357d7da3b83567238aca30456d3a`.

The artifact contains exact instrument responses, books responses, server-time responses, immutable execution-quote snapshots, hashes, observation records, diagnostics and workflow provenance. No account or order endpoint was accessed.

## Deployment interpretation

This experiment measures only preliminary public spread and transport timing. It does not alter the canonical 5 bps historical strategy metrics and does not make the strategy paper- or live-eligible. Benchmark-relative evidence, fold/year stability, execution-delay robustness, USD 1 million capacity, the consumed SOL holdout, and prospective strategy performance remain failed or blocked.

## Limitations

- The sample is brief and represents one collection window, not time-of-day or regime coverage.
- Top-of-book quantity is not a fill guarantee or nonlinear impact model.
- Collection completeness failed because of intermittent clock-domain validation errors.
- Slippage, impact, partial fills, rejections and decision-to-order latency remain unmeasured.
- BTC-USDT and ETH-USDT remain development markets; SOL-USDT remains a consumed holdout.
