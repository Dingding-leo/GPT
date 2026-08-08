# Canonical E2160 primary-benchmark robustness closure — 1H v1

## Disposition

Terminal verdict:

`reject_canonical_e2160_as_robust_primary_strategy_benchmark_1h_v1`

The canonical 2,160H daily long/cash rule remains useful as a descriptive historical comparator, but it no longer qualifies as a robustness-qualified primary architecture anchor for future promotion decisions.

This closure creates no executable candidate, uses no new market row, opens no new OOS observation, performs no fit or parameter search, and changes no canonical strategy code. Candidate/grid remain `0/0`. Exactly 5 bps one-way remains bound wherever the underlying executable evidence used costs.

## Evidence reconciliation

A predeclared provenance defect was detected in issue #1114 before closure: its Unit B text binds issue #562 head `7dfe074...`, workflow `30361641250`, artifact `8689946218`. That object is the superseded close-to-close C0 attribution artifact. The terminal #562 record explicitly supersedes it and binds exact head `1609c75f398b0cbf93b8d44391d9eaa52f10d18c`, workflow `30361747798`, artifact `8689948931`, SHA-256 `dc6da3988a80f7b8854062f23785327848bbf4ff53bb0a12183906bec280b1b4`.

Issue #1114 requires fail-closed handling on an immutable-identity mismatch, so the mismatch is recorded rather than silently rewritten. It does not create a favourable ambiguity: the terminal executable next-open replication is also rejected.

## Independent evidence dimensions

### A — BTC/ETH reference economics

Phase-0 B1 provenance reproduces. Reference development OOS economics are positive under exactly 5 bps one-way accounting:

- BTC OOS `+119.681980%`, Sharpe `+0.953765`.
- ETH OOS `+74.516034%`, Sharpe `+0.645628`.

These are descriptive reference economics, not an independent validation vote. Training economics are negative in both markets.

### B — independent cross-market replication

Terminal #562 executable next-open evidence remains rejected. The frozen six-market cohort has only `3/6` positive markets, worst-market return `-61.00%`, only `1/6` markets reaching at least `6/12` profitable folds, negative median buy-and-hold residual Sharpe, and a non-positive dependence-aware lower bound (`-26.85%`) for the cross-market median annualized mean.

Therefore the original replication gate does not pass.

### C — positive-regime stationarity

#808 passes `0/2` markets. BTC and ETH each have only three positive-net regimes, only `2/6` positive folds and `1/3` positive years, strong positive-contribution concentration, negative day-weight net opportunity, and non-positive uncertainty lower bounds. Development OOS remained unread.

Therefore the original bilateral stationarity premise does not pass.

### D — all-phase robustness

#1110 shows that 00UTC itself is not the problem: all `24/24` phases have positive OOS return and Sharpe in both BTC and ETH, and the +1H latency replay is also broadly positive.

The robustness audit still fails because `0/24` phases in either market reach `7/12` profitable self-contained OOS folds and the 5,000×168H median-path mean/Sharpe lower bounds cross zero. The failure is episode breadth and dependence, not decision-clock luck.

## Frozen programme gates

Pass: reference provenance/phase-0 parity, positive BTC/ETH reference OOS point economics, no post-hoc deletion/ranking, leave-one-dimension-out fail-closed consistency, and no aggregate override of failed robustness gates.

Fail: independent cross-market replication, positive-regime stationarity, and 24-phase bilateral robustness.

Result: `5/8` gates pass. Any failure is terminal under the preregistered closure.

Every leave-one-validation-dimension-out subset still contains at least one independent failed unit; no omitted evidence dimension can turn the programme into support.

## Strategy consequence

No completed training protocol authorizes a correction to the frozen prospective BTC/ETH rule. No threshold, phase, horizon, market subset, regime filter, hysteresis, sizing rule, or post-hoc B1 rescue is authorized. The current prospective shadow can continue unchanged for continuity, but future architecture promotion should not require beating or conditioning on B1 as if it were independently robustness-qualified.

Paper and live trading authority remain false.
