# Executable `1Dutc` signal, quote, and binding gate

This guide documents the implemented boundary from a completed OKX daily candle to an immutable target-position intent, then to a provider-neutral as-of quote, durable quote replay, and a reconstructable quote-to-intent binding. It is a read-only/offline operator example, not an order-submission guide.

## Implemented boundary

Current `main` provides:

- `fetch_okx_history_candles()` for public, completed OKX candles;
- `sample_okx_server_time_with_response()` for the unauthenticated public-time endpoint;
- `build_okx_completed_bar_cutoff()` for a bounded completed-bar availability decision;
- `write_okx_live_timing_response_evidence()` and its hash-verifying reader;
- `build_target_position_intent()` for immutable signal-to-intent translation;
- `ExecutionQuoteSnapshot` for canonical provider-neutral top-of-book evidence;
- `record_execution_quote_evidence()` and `load_execution_quote_evidence_store()` for private, immutable quote persistence and replay;
- `bind_execution_quote()` for binding one quote to one target and decision timestamp;
- `ExecutionQuoteBinding.from_json_bytes()` and `ExecutionQuoteBinding.assert_reconstructs()` for canonical binding replay and exact reconstruction.

For a valid `1Dutc` cutoff:

- the signal bar covers exactly one UTC day and opens/closes at UTC midnight;
- the public server-time request starts after the candle snapshot was observed;
- candle and server-time observations use the same normalized OKX base URL;
- the configured default bounds are server round trip `<= 2.0` seconds and absolute midpoint clock skew `<= 5.0` seconds;
- the latest confirmed candle has closed according to OKX server time;
- the latest candle is less than one complete bar stale relative to OKX server time;
- source snapshot hashes are revalidated immediately before cutoff construction.

The first permissible downstream **intent-translation observation** is:

```text
signal_not_before_utc = max(
    candle_observed_at_utc,
    exchange_server_time_utc,
    server_time_response_received_utc,
)
```

It must be strictly later than `signal_bar_close_utc`. The target intent is active only in the half-open interval:

```text
[decision_not_before_utc, expires_at_utc)
```

For `1Dutc`, expiry is the next scheduled UTC daily-bar close.

A quote may be bound to a paper-decision timestamp only when all implemented checks pass:

```text
quote.instrument_id == intent.instrument_id
quote_observed_at_utc >= decision_not_before_utc
quote_received_at_utc < decision_at_utc
decision_at_utc < expires_at_utc
decision_at_utc - quote_observed_at_utc <= maximum_age_ms
```

`maximum_age_ms` measures quote observation-to-decision age. It is not server round trip, exchange latency, order latency, or a fill assumption.

`bind_execution_quote()` produces a canonical `ExecutionQuoteBinding` with a deterministic `binding_id`. The binding records the exact target-intent ID, quote-snapshot ID, decision timestamp, freshness policy, quote timestamps, instrument-metadata hash, and observed spread. It is still market-timing evidence only: it is not risk approval, an order intent, submission, acceptance, rejection, fill, cash transition, or PnL.

## Executable deterministic example

After installing the project, run:

```bash
python examples/signal_intent_timing.py \
  --output-dir reports/examples/signal-intent-timing
```

The command performs no network or account access. It:

1. verifies the repository's immutable real OKX BTC-USDT `1Dutc` fixture SHA-256;
2. reconstructs the completed-candle snapshot through the production parser;
3. replays the captured public-time response used by the repository regression;
4. builds the completed-bar cutoff;
5. writes and rereads canonical response-bound timing evidence;
6. translates the cutoff into one canonical `TargetPositionIntent`;
7. builds and canonically replays one explicitly structural `ExecutionQuoteSnapshot`;
8. records that quote in the production private evidence store and replays the deterministic store root;
9. calls `bind_execution_quote()` at the documented decision timestamp;
10. canonically replays the resulting `ExecutionQuoteBinding`;
11. calls `ExecutionQuoteBinding.assert_reconstructs()` against the original intent and quote;
12. prints one deterministic JSON summary.

It writes:

```text
reports/examples/signal-intent-timing/okx-live-timing-response.json
reports/examples/signal-intent-timing/execution-quotes/<snapshot_id>.json
```

Running the command again with identical inputs is idempotent. A different payload at the same timing-evidence path fails closed rather than being overwritten. The quote store also treats an identical quote retry as idempotent and replays the same deterministic store SHA-256.

The candle and public-time portions use immutable real OKX evidence. The quote portion is deliberately labelled `structural_only_no_public_quote_producer`: its structural quote bytes are not a captured OKX top-of-book response. It demonstrates the exact current domain, timing, identity, persistence, and replay contract only. It does not establish executable-market provenance and must not be used as paper/live quote evidence.

The quote store is POSIX-only, requires a current-user-owned directory with mode `0700`, and requires snapshot and lock files with mode `0600`. It rejects unsafe paths, permissions, ownership, links, conflicting bytes, and noncanonical replay.

The example serializes and replays the binding in memory. Current `main` does not persist the binding in a production evidence store.

## Reproduced timeline

The deterministic repository example produces:

| Evidence event | Timestamp |
|---|---|
| Signal bar opens | `2026-07-20T00:00:00Z` |
| Signal bar closes | `2026-07-21T00:00:00Z` |
| Candle snapshot observed | `2026-07-21T11:59:59Z` |
| Public-time request starts | `2026-07-21T12:00:00Z` |
| OKX exchange server time | `2026-07-21T12:00:00.100000Z` |
| Public-time response received | `2026-07-21T12:00:00.200000Z` |
| Intent translation first permitted | `2026-07-21T12:00:00.200000Z` |
| Structural quote observed | `2026-07-21T12:00:00.300000Z` |
| Structural quote received | `2026-07-21T12:00:00.350000Z` |
| Quote binding decision timestamp | `2026-07-21T12:00:00.400000Z` |
| Intent expires | `2026-07-22T00:00:00Z` |

The persisted `availability_delay_seconds` is `43200.1`: the distance from the scheduled bar close to the observed OKX server time. It is **not** network latency, spread, slippage, market impact, or an order delay. The separately recorded server round trip is `0.2` seconds and midpoint clock skew is `0.0` seconds for this replay.

The quote binding uses `maximum_age_ms=200`; the structural quote is 100 milliseconds old at the binding decision timestamp. A 201 millisecond age fails closed. The quote receipt must also be strictly earlier than the decision timestamp.

## Quote-store identity and replay

Each persisted quote is named `<snapshot_id>.json`. Replay parses every canonical record, verifies that the filename matches the content-addressed snapshot ID, orders snapshots deterministically, and hashes the concatenated canonical bytes into one store SHA-256.

An identical retry returns the same store. A conflicting record, unsafe file type, link count, ownership, permission, path replacement, lock replacement, or unrecoverable staged publication fails closed. Crash-left safe stages are recovered under the store lock before replay.

The store root proves the ordered set of canonical quote records. It does not prove that the external response bytes addressed by `source_response_sha256` or the instrument bytes addressed by `instrument_snapshot_sha256` are available.

## Binding identity and replay

The canonical binding contains:

```text
binding_id
target_intent_id
quote_snapshot_id
instrument_id
decision_at_utc
maximum_age_ms
quote_observed_at_utc
quote_received_at_utc
instrument_snapshot_sha256
observed_spread_bps
schema_version
```

`binding_id` is the SHA-256 of the canonical binding payload. Canonical replay rejects duplicate fields, unsupported schemas, noncanonical timestamps or decimals, altered IDs, stale records, and noncanonical JSON bytes.

`ExecutionQuoteBinding.assert_reconstructs(intent, quote)` reruns the quote timing checks and then requires exact equality with a newly generated binding. A valid but different intent or quote therefore cannot be substituted after the binding is created.

## What these timestamps and IDs are not

`signal_not_before_utc` is not an order timestamp, quote timestamp, submission timestamp, acceptance, rejection, partial fill, fill, or executable price. It proves only that the completed signal may be translated after the latest required availability observation.

A valid `ExecutionQuoteBinding` is not an order-intent ID. It proves only that one canonical quote was usable for one target intent at one decision timestamp under one freshness policy.

Current `main` still has no integrated public OKX top-of-book producer, instrument-constrained sizing, persisted quote-to-intent binding, paper broker, order/fill journal, cash transition, or reconciliation loop. A future data adapter must bind `source_response_sha256` and `instrument_snapshot_sha256` to actual immutable public response and instrument-metadata artifacts before a quote can be used as paper evidence.

Do not use the candle close, `signal_not_before_utc`, bid, ask, midpoint, `snapshot_id`, `binding_id`, or quote-store root as a guaranteed fill price or proof of order submission. Do not infer a one-second, same-candle, bid, ask, or midpoint-fill convention from this guide.

## Quote identity and spread boundary

`ExecutionQuoteSnapshot` binds provider and instrument identity, exchange-observed and locally received UTC timestamps, canonical bid/ask prices and quantities, source-response and instrument-snapshot SHA-256 values, and a deterministic `snapshot_id`.

Observed spread is derived separately:

```text
spread_bps = (ask_price - bid_price) / midpoint * 10_000
```

It is market evidence, not the 5 bps research fee, not slippage, not impact, and not latency.

## Cost boundary

The research selection baseline remains a **5 bps one-way exchange fee** per unit of absolute position turnover. The `7.5`, `10`, and `15` bps scenarios remain fixed-selected-path total-cost sensitivities.

Spread, slippage, market impact, and latency remain separate and unmeasured. Neither the timing evidence, target intent, quote snapshot, quote store, nor quote binding converts those components into the 5 bps fee or claims an executable fill.

## Fail-closed operator conditions

The completed-bar and intent boundary rejects mutated source evidence, unconfirmed or stale bars, invalid exchange-time ordering, excessive timing uncertainty, invalid daily-bar geometry, invalid activation/expiry, and malformed intent fields.

The quote-store and binding boundary additionally rejects:

- a quote for another instrument;
- a quote observed before intent activation;
- a quote received at or after the decision timestamp;
- a decision before activation or at/after intent expiry;
- a quote older than the configured maximum age;
- crossed, zero-size, noncanonical, or tampered quote records;
- unsafe quote-store permissions, ownership, file types, links, paths, or locks;
- conflicting bytes for an existing snapshot ID;
- a binding with an altered target ID, quote ID, decision timestamp, age policy, spread, or instrument hash;
- a binding reconstructed against a different otherwise-valid intent or quote.
