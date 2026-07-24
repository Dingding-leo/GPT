# Executable OKX instrument, quote, and paper-attempt constraint gate

This guide documents one offline, read-only execution boundary implemented on current `main`.
It verifies immutable public OKX instrument and depth-one quote evidence, then executes the
current limit-order and paper-attempt constraint validators. It does not connect to an
account, submit an order, read balances, or claim an exchange fill.

## Current timeframe boundary

Current `main` still produces canonical research only for `1Dutc`. That path is retained as
the benchmark. There is no implemented, verified `1h` research command or paper loop yet,
and there is no implemented `15m` path.

This example is therefore deliberately timeframe-neutral. It documents exchange evidence
and pure pre-adapter validation that a future `1h` paper loop can reuse. It must not be
presented as a completed intraday signal, maker-order, or paper-broker workflow.

## Run the implemented offline gate

After installing the project, execute:

```bash
python examples/okx_spot_instrument_replay.py \
  --output-dir reports/examples/okx-spot-instrument
```

The command performs no network request. It uses immutable official OKX documentation
extracts whose provider-response SHA-256 digests are pinned in the executable:

```text
public instrument response:
290bd86ecbb1683351993197b0ec18001dfb604b9ba1cb864d9d6d327855f0eb

public depth-one books response:
7d12a351f8f51320d1c8beee0063557e1c90388d66ac63412bf66ca544aeb3e3

public-time response:
2ab44b9abd247acb72cf79b22b30e14c4e80cc00a96384a4535b31a37f6dfeb0
```

The example executes this sequence:

```text
pinned public-instruments bytes
→ exact instrument parse and timing envelope
→ content-addressed archive and replay
→ pinned depth-one books and public-time bytes
→ reconstructable top-of-book evidence
→ deterministic non-contemporaneous constraint envelope
→ immutable target intent and quote binding
→ submission-time quantity and limit-price validation
→ partial paper-attempt construction and canonical replay
→ requested/fill lot validation and visible-touch capacity check
```

The deterministic constraint envelope is necessary because the official instrument and
books examples were published at different times. It reuses the exact public price,
quantity, and source hashes only to execute pure validators. It is not provider evidence
that those records existed together, and `paper_order_eligible` must remain `false`.

A successful run reports the following material fields:

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
paper_attempt_probe.lot_aligned=true
paper_attempt_probe.within_visible_touch=true
paper_attempt_probe.replay_equal=true
paper_attempt_probe.reconstructs=true

timeframe_status.current_main_research=1Dutc_benchmark_only
timeframe_status.intraday_1h=not_implemented
timeframe_status.intraday_15m=not_implemented

account_connectivity=disabled
order_submission=not_performed
paper_order_eligible=false
```

## Implemented constraint meaning

The limit-order probe calls `validate_okx_spot_limit_order_constraints()` at the exact
submission timestamp. Passing proves only that:

- the supplied instrument snapshot is available, live, and within the configured age;
- the submission precedes any declared instrument validity cutoff;
- requested base quantity is canonical, at least `minSz`, and an exact `lotSz` multiple;
- limit price is canonical and an exact `tickSz` multiple.

The paper-attempt probe then calls
`validate_okx_paper_execution_attempt_constraints()`. Passing additionally proves that:

- the quote references the exact immutable instrument response;
- the paper attempt references and reproduces the supplied quote;
- requested quantity passes the same submission-time instrument checks;
- non-zero filled quantity is an exact `lotSz` multiple;
- claimed fill quantity does not exceed the supplied same-side top-of-book quantity;
- canonical attempt bytes replay to the same `attempt_id`;
- intent, binding, quote, timestamps, quantities, and outcome reconstruct exactly.

The example uses a partial buy probe of `0.04 BTC` against a request for `0.1 BTC`. This is
a deterministic domain-validation example, not evidence that OKX accepted or filled an
order.

## What is not implemented

Current `main` does not yet provide an executable maker/post-only order lifecycle. The
current `PaperExecutionAttempt` record uses the provider-neutral
`market-vwap-at-touch-or-worse` fill convention and supports structural
`accepted`, `rejected`, `partial`, and `filled` outcomes. It does not provide:

- maker/post-only placement or maker-price improvement logic;
- exchange order IDs or an adapter idempotency key;
- order expiry, queue position, no-fill, timeout, cancel, or requote events;
- fill probability or deeper-book liquidity;
- a public OKX minimum quote-notional source;
- risk-approved cash, positions, or notional limits;
- durable order, fill, cash, portfolio, or PnL state on current `main`;
- restart recovery, reconciliation, kill switches, monitoring, or rollback;
- a verified `1h` or `15m` signal and order cutoff.

Do not infer these capabilities from a successful constraint probe.

## Fee and execution-diagnostic boundary

Research and paper PnL use exactly a **5 bps one-way exchange fee** per unit of absolute
position turnover. This example adds no other modeled cost to PnL.

The exact observed bid/ask spread is reported as a diagnostic. Quote and decision
timestamps expose latency evidence. Slippage and market impact remain `not_modeled`.
None of those diagnostics is hidden inside the 5 bps fee, and this command computes no
strategy return or PnL.

`minSz` is a minimum base-asset quantity. Multiplying it by the observed bid or ask gives
a quote-equivalent arithmetic value for this fixture; it is not an exchange minimum
quote-notional rule.

## Fail-closed operator conditions

Stop the paper decision when any of these conditions is true:

- provider bytes or fixture metadata do not match the digest pinned in the executable;
- quote evidence is not bound to the supplied instrument response;
- instrument or quote replay differs from canonical bytes;
- server-time chronology, round trip, clock skew, response hash, or configured policy
  cannot be reconstructed;
- instrument status is not `live`, continuous trading has not started, the instrument is
  expired, or a validity cutoff has been reached;
- instrument or quote evidence is stale at the relevant decision or submission timestamp;
- requested quantity is noncanonical, below `minSz`, or off `lotSz`;
- limit price is noncanonical or off `tickSz`;
- the paper attempt references another quote, instrument, or source response;
- filled quantity is off `lotSz` or exceeds supplied same-side touch quantity;
- minimum quote-notional policy, risk approval, durable state, reconciliation, or kill
  switches are required but unavailable.

The executable's stdout is evidence from an offline validation probe. It is not an order
intent for an adapter, exchange acknowledgement, broker fill, portfolio transition, or
PnL record.
