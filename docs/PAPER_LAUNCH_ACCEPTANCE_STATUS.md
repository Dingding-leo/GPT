# Paper and limited-capital launch acceptance status

This document records the operator-visible status of the current release train. It is
fail-closed: it documents only commands and controls that exist in the checked-out code.
It does not provide credentials, account connectivity, private endpoint access, order
submission, or a live-enable procedure.

## Current release boundary

The canonical immutable public-OKX `1H` evidence gate is now on `main` through PR #475.
The executable release train still stops before G1 because the current BTC-USDT and
ETH-USDT strategy paths are research-rejected. The `1Dutc` path remains the benchmark
and `15m` remains blocked.

Research and paper PnL use exactly **5 bps one-way exchange fee** on filled notional
only. Spread, slippage, market impact, latency, fill quality, no-fill, partial-fill,
timeout, cancellation, requote, and adverse selection remain separate diagnostics or
event outcomes.

The merged G0 consumer verifies each artifact manifest, copies every manifested file
into a private temporary tree with regular-file, single-link, `O_NOFOLLOW`, inode, and
SHA-256 checks, reconstructs promotion and provider provenance from that private copy,
and then re-verifies the source artifact and pinned manifest digest. A successful G0
workflow therefore establishes evidence integrity; it does not establish strategy,
paper, or limited-capital eligibility.

## Current authorization state

The persisted per-market and cross-market gates enforce:

```text
cross_market_candidate_eligible = false
allow_15m_evaluation = false
allow_paper_promotion = false
allow_limited_capital = false
```

Current operator authorization remains:

```text
paper_start_authorized = false
limited_capital_authorized = false
account_connectivity = absent
order_submission = absent
```

## Verification command and evidence rule

The following sequence is the repository contract for this status document and its
fail-closed source bindings:

```bash
python -m pip install -e ".[dev]"
python -m pip check
pytest -q tests/test_paper_launch_acceptance_status_documentation.py
```

The presence of these commands in documentation or a workflow definition is not
execution evidence. For every reviewed head, operators must record the immutable commit
SHA, workflow run ID, final conclusion, artifact ID, and artifact SHA-256 when an
artifact is emitted. A missing run is **UNVERIFIED**, not a pass or a failure. Historical
green runs cannot authorize a moved PR head or a squash-merged `main` commit.

G0 completion requires successful exact-head results for all four current workflows:

```text
Python Package Build
Hourly Quant Research
Canonical BTC ETH 1h Research
OKX 1H Data Coverage
```

Until all four results are recorded on one unchanged `main` SHA, the release decision
remains **BLOCKED** and G1 must not start. The documentation contract test verifies the
executable promotion gate, cross-market gate, workflow permissions, exact 5 bps
economics, secure artifact materialization, and disabled paper/capital permissions. It
does not start a paper runtime.

## Operator command inventory

| Capability | Status | Executable operator evidence |
|---|---|---|
| Canonical `1H` acquisition, replay, and promotion evidence | **IMPLEMENTED; EXACT-HEAD EVIDENCE REQUIRED** | `.github/workflows/intraday-1h-research.yml` executes public exact-byte acquisition, persisted replay, 5 bps verification, portable manifests, secure semantic reconstruction, and fail-closed blocker publication. Its definition or a historical run is not current-head execution evidence. |
| Paper startup and shutdown | **BLOCKED** | No executable paper-runner startup or shutdown command exists on `main`. |
| Health, heartbeat, and event-loop status | **BLOCKED** | No unattended paper runtime publishes an operator health or heartbeat contract. |
| Restart recovery and reconciliation | **BLOCKED** | Journal and replay primitives do not form one integrated startup-recovery command with a zero-drift reconciliation result. |
| Stale-data and risk kill switches | **BLOCKED** | Risk and stale-data primitives are not integrated into a durable unattended runtime with operator-visible latch state and authenticated manual release. |
| Daily paper ledger | **BLOCKED** | No canonical daily command produces one reconciled cash, position, order, fill, fee, reservation, and risk-state ledger. |
| Maker execution acceptance | **BLOCKED** | Structural maker replay does not authorize terminal outcomes without complete public-trade and top-of-book coverage from submission through exclusive expiry. |
| Forward drift classification | **BLOCKED** | No prospective paper run compares immutable research targets with reconstructed paper decisions, attempts, state roots, and outcomes. |
| Prospective paper acceptance scorecard | **BLOCKED** | No predeclared G5 scorecard command or accepted observation window exists. |
| Limited-capital launch or abort | **BLOCKED** | No G6 authorization record, account adapter, order adapter, or live-enable command exists. |

`BLOCKED` means there is no operator command to run. Operators must not invent a
command, interpret a unit-test fixture as a paper session, or substitute historical or
structural replay for prospective operation.

## Incident containment and rollback

Because no paper or live runtime is authorized, the current containment procedure is to
leave all adapters disabled, preserve immutable artifacts and audit records, and stop at
the failed gate. There is no executable runtime rollback or restart command to document.
A future rollback procedure must not erase persisted risk latches, event hashes, journal
history, or reconciliation roots.

## Evidence required before G5

A reviewed release path must bind all of the following before an unattended paper run
can be authorized:

1. one frozen G1 strategy that passes the declared cross-market `1H` research gates;
2. deterministic G2 maker lifecycle evidence for acknowledged, rejected, no-fill,
   partial-fill, filled, timeout, cancelled, and requote outcomes;
3. G3 atomic cash, position, open-order, fill, fee, reservation, risk-high-watermark,
   migration, restart-recovery, idempotency, and reconciliation state;
4. G4 stale-data, loss, drawdown, turnover, and reconciliation kill switches plus
   heartbeat, alerting, and observability;
5. an immutable prospective-paper configuration, start time, strategy ID, source
   artifact roots, acceptance window, and scorecard thresholds declared before the
   first paper observation.

Until that evidence exists, paper startup, shutdown, health, recovery, daily-ledger,
forward-drift, and acceptance-scorecard procedures remain explicitly blocked.

## Limited-capital boundary

G6 remains a separate manual authorization after an accepted G5 run. A future
limited-capital checklist must fail closed on any artifact mismatch, reconciliation
drift, stale-data condition, missing heartbeat, alert failure, active risk latch,
recovery failure, or deviation from the frozen strategy and execution contracts. These
are launch blockers, not claims that an automated abort path currently exists.
