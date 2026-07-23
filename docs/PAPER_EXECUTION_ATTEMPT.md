# Executable paper-execution-attempt gate

This guide documents the exact provider-neutral paper-attempt record implemented on current `main`. It is an offline domain/replay check. It does not connect to an account, submit an order, claim an exchange fill, persist broker state, update cash or positions, or compute PnL.

## Run the implemented gate

After installing the project, execute:

```bash
python examples/paper_execution_attempt_replay.py
```

The command has no network path. It deterministically constructs:

```text
TargetPositionIntent
→ ExecutionQuoteSnapshot
→ ExecutionQuoteBinding
→ explicit submission-time intent check
→ PaperExecutionAttempt
→ canonical JSON replay
→ exact intent/binding/quote reconstruction
```

The example prints one canonical JSON summary containing `intent_id`, `quote_snapshot_id`, `binding_id`, `attempt_id`, chronology, quantities, reference bid/ask, measured timestamp deltas, and the explicit cost-component boundary.

The quote is labelled `structural_only_not_exchange_fill_evidence`. Its prices exercise the implemented schema and conservative paper convention only. They are not a captured top-of-book response and cannot support a paper/live execution or performance claim.

## Required caller-side intent check

Current `record_paper_execution_attempt()` accepts an `ExecutionQuoteBinding` and `ExecutionQuoteSnapshot`; it does not receive the original `TargetPositionIntent`. The example therefore performs this executable check immediately before recording the attempt:

```python
intent.assert_active_at(submitted_at_utc)
```

The intent lifetime is half-open: `[decision_not_before_utc, expires_at_utc)`. A submission at `expires_at_utc` is expired and must not proceed. This caller-side check is mandatory for the documented current-main procedure; do not infer that the factory independently revalidates intent expiry at submission.

## Implemented chronology and freshness

The example uses:

| Event | UTC timestamp |
|---|---|
| Signal bar close | `2026-07-21T00:00:00.000000Z` |
| Intent active from | `2026-07-21T00:00:00.200000Z` |
| Quote observed | `2026-07-21T00:00:00.300000Z` |
| Quote received | `2026-07-21T00:00:00.350000Z` |
| Binding decision | `2026-07-21T00:00:00.400000Z` |
| Paper submission | `2026-07-21T00:00:00.450000Z` |
| Paper outcome | `2026-07-21T00:00:00.500000Z` |
| Intent expires | `2026-07-22T00:00:00.000000Z` |

The implemented record requires:

```text
quote_observed_at_utc <= quote_received_at_utc
quote_received_at_utc < decision_at_utc
decision_at_utc < submitted_at_utc < outcome_at_utc
submitted_at_utc - quote_observed_at_utc <= maximum_age_ms
```

The example uses `maximum_age_ms=250`; quote observation-to-submission age is `150 ms`.

## Outcome and fill-price contract

`PaperExecutionAttempt` supports exactly `accepted`, `rejected`, `partial`, and `filled`.

- `accepted` and `rejected` contain zero filled quantity and zero average fill price.
- `partial` requires `0 < filled_base_quantity < requested_base_quantity` and a positive average price.
- `filled` requires filled quantity to equal requested quantity and a positive average price.
- A paper buy fill cannot be priced better than the reference ask.
- A paper sell fill cannot be priced better than the reference bid.
- The fixed convention string is `market-vwap-at-touch-or-worse`.

These checks prevent internally inconsistent paper records. They do not model queue position, depth consumption, exchange rejection rules, partial-fill evolution, spread crossing beyond the stored price, or an actual broker response.

## Canonical replay and identity

The public replay APIs used by this gate are `PaperExecutionAttempt.from_json_bytes()` and `PaperExecutionAttempt.assert_reconstructs()`.

The example runs:

```python
replayed = PaperExecutionAttempt.from_json_bytes(attempt.to_json_bytes())
replayed.assert_reconstructs(intent, binding, quote)
```

Canonical replay rejects duplicate JSON fields, unsupported schema versions, noncanonical timestamps or decimal strings, altered latency fields, an altered `attempt_id`, and quantity/price/outcome inconsistencies. `assert_reconstructs()` reruns binding reconstruction and recreates the attempt from the exact quote and recorded values.

The deterministic `attempt_id` is a content hash of the canonical attempt payload. It is not an exchange order ID, idempotency key accepted by a broker, reconciliation root, or proof that an order was submitted.

## Cost separation

The research baseline remains a **5 bps one-way exchange fee** per unit of absolute position turnover. The example reports observed structural spread separately.

Spread, slippage, market impact, and latency remain separate. Latency is recorded only as timestamp-derived microseconds and is not converted into a price cost. The `7.5/10/15 bps` values remain fixed-selected-path all-in research sensitivities; they are not measured paper-attempt costs and are not hidden inside the 5 bps fee.

## Fail-closed operator boundary

Treat the command as successful only when it exits zero and prints:

```text
account_connectivity = disabled
order_submission = not_performed
persistence_status = not_implemented
intent_active_at_submission = true
```

Any replay, reconstruction, chronology, freshness, quantity, price, or intent-lifetime failure is a paper-operation blocker.

This record is **not durable broker state**. Current `main` does not provide a production paper-attempt journal, atomic state transition, before/after portfolio state, cash ledger, restart recovery, reconciliation, kill switch, alert, or PnL reconstruction. Do not launch a long-running paper worker by treating this example file or stdout as those missing facilities.
