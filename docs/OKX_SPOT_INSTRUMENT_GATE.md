# Executable OKX paper-attempt constraint gate

This guide documents one offline, read-only boundary implemented on current `main`. It
verifies immutable public OKX instrument and depth-one quote bytes, then executes the
current limit-order and paper-attempt constraint validators. It does not connect to an
account, submit an order, read balances, or claim an exchange fill.

## Current timeframe truth

Current `main` still produces canonical research only for `1Dutc`; retain that path as the
benchmark. There is no implemented, verified `1h` research command or paper event loop,
and no implemented `15m` path.

This example is timeframe-neutral. It documents exchange constraints that a future `1h`
paper loop can reuse without pretending that the intraday signal, cutoff, maker order, or
broker lifecycle already exists.

## Run the implemented gate

After installing the project, execute:

```bash
python examples/okx_spot_instrument_replay.py \
  --output-dir reports/examples/okx-spot-instrument
```

The command performs no network request. It pins exact official OKX documentation
extracts:

```text
public instrument response SHA-256:
290bd86ecbb1683351993197b0ec18001dfb604b9ba1cb864d9d6d327855f0eb

public depth-one books response SHA-256:
7d12a351f8f51320d1c8beee0063557e1c90388d66ac63412bf66ca544aeb3e3
```

The executable sequence is:

```text
pinned public-instruments bytes
→ exact instrument parse and timing envelope
→ content-addressed archive and idempotent retry
→ pinned depth-one quote bytes
→ deterministic non-contemporaneous constraint envelope
→ immutable target intent and quote binding
→ submission-time quantity and limit-price validation
→ partial paper-attempt construction and canonical replay
→ requested notional, fill lot, fill tick, and visible-touch validation
```

The official instrument and books examples were published at different times. Their exact
values are re-timed only inside a deterministic structural validation envelope. This is
not evidence that the records existed together, and `paper_order_eligible` remains
`false`.

A successful run reports these material fields:

```text
canonical_research_economics.exchange_fee_bps_one_way=5.0
canonical_research_economics.additional_execution_costs_in_pnl=none

constraint_probe.status=passed
constraint_probe.base_quantity=0.1
constraint_probe.limit_price=41006.8

paper_attempt_probe.status=passed
paper_attempt_probe.outcome=partial
paper_attempt_probe.requested_base_quantity=0.1
paper_attempt_probe.filled_base_quantity=0.04
paper_attempt_probe.fill_fraction=0.4
paper_attempt_probe.minimum_paper_quote_notional_policy=10
paper_attempt_probe.requested_quote_notional_at_ask=4100.68
paper_attempt_probe.replay_equal=true
paper_attempt_probe.reconstructs=true

timeframe_status.current_main_research=1Dutc_benchmark_only
timeframe_status.intraday_1h=not_implemented
timeframe_status.intraday_15m=not_implemented

account_connectivity=disabled
order_submission=not_performed
paper_order_eligible=false
```

## Run the fail-closed constraint regressions

The successful probe is not sufficient evidence by itself. Execute the three operator-facing
negative checks that prove the current boundary rejects off-tick prices, off-lot partial
fills, and a request below the explicitly declared paper quote-notional floor:

```bash
pytest tests/test_okx_spot_instrument_replay_example.py \
  -k 'rejects_off_tick_limit_price or rejects_off_lot_partial_fill or rejects_requested_notional_below_declared_paper_floor'
```

Expected result:

```text
3 passed, 4 deselected
```

These regressions remain offline. They structurally substitute an off-tick `41006.85`
limit price, an off-lot `0.040000005 BTC` partial fill, and a `5000 USDT` paper-policy
floor above the deterministic `4100.68 USDT` requested touch notional. Each case must fail
before any adapter boundary. The tests perform no network request, account access, or order
submission.

## Implemented constraint meaning

`validate_okx_spot_limit_order_constraints()` proves only that:

- the supplied instrument snapshot is live and fresh at submission;
- the submission precedes any declared validity cutoff;
- requested base quantity is canonical, at least `minSz`, and an exact `lotSz` multiple;
- limit price is canonical and an exact `tickSz` multiple.

`validate_okx_paper_execution_attempt_constraints()` additionally proves that:

- the quote references the exact immutable instrument response;
- the attempt references and reproduces the supplied quote;
- requested quantity meets the same submission-time constraints;
- requested quantity times the conservative same-side touch is at least the explicit
  caller-declared paper minimum quote notional;
- non-zero filled quantity is an exact `lotSz` multiple;
- average fill price is an exact `tickSz` multiple;
- claimed fill does not exceed supplied same-side top-of-book quantity.

The example declares a **10 USDT paper-policy floor**. This is a versioned caller policy,
not a minimum reported by the public OKX instrument endpoint. The public endpoint's
`minSz` remains a minimum base-asset quantity.

The partial `0.04 BTC` fill against a `0.1 BTC` request is a deterministic domain probe,
not evidence that OKX accepted or filled an order.

## What remains unimplemented

Current `main` does not provide an executable maker/post-only order lifecycle. The current
`PaperExecutionAttempt` uses the provider-neutral
`market-vwap-at-touch-or-worse` convention and supports structural `accepted`, `rejected`,
`partial`, and `filled` outcomes. It does not provide:

- maker/post-only placement or maker-price improvement;
- exchange order IDs or adapter idempotency keys;
- order expiry, queue position, no-fill, timeout, cancel, or requote events;
- fill probability or deeper-book capacity;
- an exchange-sourced minimum quote-notional rule;
- risk-approved cash, positions, or portfolio notional limits;
- durable order, fill, cash, portfolio, or PnL state on current `main`;
- restart recovery, reconciliation, kill switches, monitoring, or rollback;
- a verified `1h` or `15m` signal and order cutoff.

Do not infer these capabilities from a successful constraint probe.

## Fee and execution-diagnostic boundary

Research and paper PnL use exactly a **5 bps one-way exchange fee** per unit of absolute
position turnover. This executable adds no other modeled cost to PnL.

Observed bid/ask spread and timestamps are separate diagnostics. Slippage and market
impact remain `not_modeled`; latency is recorded only as timestamps. None is hidden inside
the 5 bps fee, and this command computes no strategy return or PnL.

## Fail-closed operator conditions

Stop the paper decision when any of these conditions is true:

- provider bytes or metadata do not match the pinned digest;
- instrument evidence is stale, inactive, expired, or past a validity cutoff;
- requested quantity is noncanonical, below `minSz`, or off `lotSz`;
- limit price is noncanonical or off `tickSz`;
- quote or attempt references another instrument or source response;
- requested quote notional is below the declared paper-policy floor;
- filled quantity is off `lotSz`, average fill is off `tickSz`, or claimed fill exceeds
  supplied same-side touch quantity;
- required risk approval, durable state, reconciliation, or kill switches are absent.

The executable's stdout is an offline validation record. It is not an adapter order
intent, exchange acknowledgement, broker fill, portfolio transition, or PnL record.
