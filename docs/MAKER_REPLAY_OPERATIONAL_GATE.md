# Maker replay operational gate

This procedure documents the repository's executable maker/post-only replay gate.
It is valid only on a checkout that contains `scripts/build_maker_replay_gate.py`.
Until that implementation reaches `main`, `1Dutc` remains the default-branch
benchmark. The gate labels `1H` as the canonical intraday research timeframe, but it
does not connect a 1h strategy target to an order intent. `15m` remains blocked until
that 1h target, order, state, replay, and paper-acceptance chain exists.

## Safety and economics

The commands are offline and consume only the checked-in official OKX public
`GET /api/v5/market/trades` documentation response for `BTC-USDT`. They do not read
credentials, balances, positions, private endpoints, or order endpoints and do not
submit, amend, cancel, or replace an exchange order.

Modeled PnL uses exactly **5 bps one-way** exchange fee on filled quote notional.
Spread, slippage, market impact, and latency remain separate diagnostics and are not
added to the fee. The pinned public response SHA-256 is:

```text
01438cc23709d9c8e9ea8d9d49d3f64c65978d27d592356a333f7a3da213d563
```

The source is a historical documentation example, not a current quote or trade stream
and not evidence that any strategy is paper/live eligible.

## Install and run the focused repository gate

```bash
python -m pip install -e ".[dev]"
python -m pip check
ruff check \
  scripts/build_maker_replay_gate.py \
  tests/test_maker_fill_replay.py \
  tests/test_maker_replay_gate.py \
  tests/test_maker_replay_workflow.py \
  tests/test_maker_replay_documentation.py
ruff format --check \
  scripts/build_maker_replay_gate.py \
  tests/test_maker_fill_replay.py \
  tests/test_maker_replay_gate.py \
  tests/test_maker_replay_workflow.py \
  tests/test_maker_replay_documentation.py
pytest -q \
  tests/test_maker_fill_replay.py \
  tests/test_maker_replay_gate.py \
  tests/test_maker_replay_workflow.py \
  tests/test_maker_replay_documentation.py
```

## Build immutable evidence

```bash
python scripts/build_maker_replay_gate.py \
  --source-response tests/fixtures/okx/trades-btc-usdt-docs-20220602/response.json \
  --source-metadata tests/fixtures/okx/trades-btc-usdt-docs-20220602/metadata.json \
  --output-dir reports/paper/maker-replay
```

Successful stdout is canonical JSON containing:

- `maker_order_replay_passes: true`;
- `replay_equivalent: true`;
- both `cancelled_no_fill` and `cancelled_partial` outcomes;
- a lowercase SHA-256 `manifest_sha256`.

The output directory must contain exactly:

```text
artifact-manifest.sha256
cancelled-no-fill.json
cancelled-partial.json
maker-order-replay-gate.json
source/metadata.json
source/response.json
```

The no-fill record proves that a same-price touch is diagnostic only. The partial-fill
record assigns only strict trade-through volume remaining after explicit queue-ahead
consumption. Residual quantity is cancelled at the exclusive expiry and is
requote-eligible. Neither record is an exchange fill.

## Verify persisted evidence

```bash
python scripts/build_maker_replay_gate.py \
  --output-dir reports/paper/maker-replay \
  --verify-only
(
  cd reports/paper/maker-replay
  sha256sum --check artifact-manifest.sha256
)
```

Verification must reconstruct the source snapshot, both replay records, modeled
5 bps fee, outcome inventory, execution policy, and gate JSON. A self-consistent hash
is insufficient: altered fee, quantity, outcome, timing, queue, source identity,
manifest inventory, or duplicate fields must fail closed.

## Prove deterministic regeneration

```bash
rm -rf /tmp/maker-replay-rebuilt
python scripts/build_maker_replay_gate.py \
  --source-response tests/fixtures/okx/trades-btc-usdt-docs-20220602/response.json \
  --source-metadata tests/fixtures/okx/trades-btc-usdt-docs-20220602/metadata.json \
  --output-dir /tmp/maker-replay-rebuilt
diff -ru reports/paper/maker-replay /tmp/maker-replay-rebuilt
```

A non-empty diff blocks promotion of the evidence.

## Operator interpretation

The generated gate must report:

```text
canonical_timeframe = 1H
benchmark_timeframe = 1Dutc
exchange_fee_one_way_bps = 5
fee_only_modeled_pnl = true
spread/slippage/impact/latency = separate_not_modeled
account_connectivity = disabled
order_submission = not_performed
```

The `optional_next_timeframe` value is planning metadata only. It does not authorize
15m research, paper trading, account connectivity, or order submission.

## Remaining boundaries

Passing this gate proves deterministic provider-specific replay semantics and
artifact integrity only. It does not prove that:

- a canonical 1h strategy produced the external order-intent ID;
- price and quantity satisfy current OKX tick, lot, minimum-size, and status evidence;
- public trades reveal actual queue position, hidden liquidity, self-trade prevention,
  or exchange matching priority;
- order, fill, cash, position, and risk state are durably committed;
- restart recovery, reconciliation, adapter idempotency, or kill switches pass;
- prospective paper performance or limited-capital launch acceptance passes.

Do not infer any of those gates from a successful replay artifact.
