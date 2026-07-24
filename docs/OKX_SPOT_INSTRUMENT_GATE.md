# Executable OKX instrument and top-of-book evidence gate

This guide documents the public, read-only instrument and depth-one quote boundaries implemented on
current `main`. It verifies pinned provider bytes, archives one deterministic instrument observation,
and reconstructs one complete OKX top-of-book timing envelope. It does not connect to an account,
read balances or positions, and does not submit an order.

## Run the implemented offline gate

After installing the project, execute:

```bash
python examples/okx_spot_instrument_replay.py \
  --output-dir reports/examples/okx-spot-instrument
```

The command performs no network request. It uses two immutable official OKX documentation extracts:

```text
public instrument response:
290bd86ecbb1683351993197b0ec18001dfb604b9ba1cb864d9d6d327855f0eb

public depth-one books response:
7d12a351f8f51320d1c8beee0063557e1c90388d66ac63412bf66ca544aeb3e3
```

Both digests are pinned in the executable. Each fixture sidecar must independently agree with its
pinned digest and the quote sidecar must bind to the pinned instrument response. Editing a provider
response and its sidecar together does not authorize a new evidence identity.

The command then:

1. reconstructs a bounded public server-time sample after instrument-response receipt;
2. parses the exact instrument bytes with duplicate-field rejection;
3. requires `SPOT`, `BTC-USDT`, `state=live`, valid listing/trading/expiry times, and positive
   plain-decimal constraints;
4. preserves `tickSz`, `lotSz`, and `minSz` exactly as exchange strings;
5. writes content-addressed instrument raw and metadata files and replays them;
6. parses the exact depth-one books and public-time bytes with duplicate-field rejection;
7. reconstructs the books request, receipt, public-time request/response, exchange timestamp,
   round-trip, midpoint-clock-skew, and quote-age policies;
8. serializes and replays `ReconstructableOKXTopOfBookEvidence` with identical canonical bytes and
   evidence ID;
9. derives observed spread and quote-equivalent arithmetic for the minimum base quantity while
   keeping both distinct from an exchange minimum-notional rule.

A successful deterministic run reports:

```text
state=live
tick_size=0.1
lot_size=0.00000001
minimum_order_size_base=0.00001
bid_price=41006.3
ask_price=41006.8
minimum_buy_quote_equivalent_at_observed_ask=0.410068
minimum_sell_quote_equivalent_at_observed_bid=0.410063
instrument_replay_equal=true
quote_replay_equal=true
account_connectivity=disabled
order_submission=not_performed
paper_order_eligible=false
```

`minSz` is a minimum base-asset quantity. Multiplying it by the observed bid or ask produces a
quote-equivalent value for that observation; it is not a minimum quote-notional constraint reported
by the public instrument endpoint.

## Evidence scope

Together, the command revalidates the complete instrument and quote server-time envelopes.

The instrument archive can provide evidence for instrument identity, spot status, `tickSz`, `lotSz`,
`minSz`, listing/continuous-trading/expiry timestamps, pending changes, and the complete public-time
envelope under which the response was observed.

The quote replay can provide evidence for exact bid/ask prices and quantities, exchange and local
receipt timestamps, source-response and public-time SHA-256 identities, observed spread, configured
freshness limits, and the complete books/public-time timing envelope.

The example's books fixture is the official OKX documentation response from August 26, 2021. The
instrument fixture is a separate official documentation response published in 2025. They are
immutable parser and timing evidence, not a contemporaneous market/instrument pair. The command must
therefore remain ineligible for a paper order even though each individual record reconstructs.

An exact instrument archive retry is idempotent. A conflicting content-addressed file is an
operational blocker and must not be overwritten manually. The quote replay is canonical in memory;
this command does not claim to provide a durable paper decision, order, fill, cash, portfolio, or PnL
journal.

## What remains blocked

This evidence gate is not an order-sizing approval. Current `main` does not yet invoke a single
submission-time boundary that proves the instrument snapshot is still fresh, applies
`valid_until_utc`, validates a requested quantity against `lotSz` and `minSz`, and binds that result
to risk-approved cash and portfolio state.

Do not use a daily candle close, midpoint, bid, or ask as a fill. A current books observation can
establish a decision-time market boundary and observed spread, but slippage, market impact, latency
pricing, broker acceptance, partial fills, rejections, and portfolio transitions require separate
paper-execution evidence.

## Cost boundary

The research declaration remains a **5 bps one-way exchange fee** per unit of absolute position
turnover.

Observed spread is reported separately; spread, slippage, market impact, and latency remain distinct;
slippage and market impact remain unmodelled, and latency is timestamp evidence only rather than a
priced cost. The `7.5/10/15 bps` values remain fixed-selected-path all-in research sensitivities.
Spread, slippage, market impact, and latency are not hidden inside the 5 bps fee.

## Fail-closed operator conditions

Stop the paper decision when any of these conditions is true:

- exact provider bytes or a sidecar do not match the digest pinned in the executable;
- the quote sidecar is not bound to the pinned instrument response;
- replayed instrument or quote fields differ from exact provider bytes;
- either server-time chronology, round trip, clock skew, response hash, or configured policy cannot
  be reconstructed and revalidated;
- the instrument is not `live`, has not begun continuous trading, is expired, or has reached
  `valid_until_utc`;
- the quote is stale, crossed, malformed, from another instrument, or not received before the paper
  decision;
- a requested quantity has not passed the implemented submission-time lot/minimum-size boundary;
- risk-approved cash, portfolio state, broker event persistence, or reconciliation evidence is
  absent.

The executable example is an evidence and replay gate only. Its stdout is not an order intent,
exchange acknowledgement, fill, cash ledger, portfolio transition, or PnL record.
