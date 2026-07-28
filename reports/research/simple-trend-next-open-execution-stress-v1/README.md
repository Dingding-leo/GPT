# Simple trend next-open execution stress v1

## Verdict

`retain_fixed_development_benchmark_pending_independent_replication`

The frozen 2,160-hour per-instrument simple-trend long/cash rule survives executable next-open alignment on the consumed BTC-USDT and ETH-USDT development window. The rule remains a benchmark only. It is not authorized for paper or live trading, and the new temporal extension produced only cash decisions rather than fresh exposed-return evidence.

## Frozen paths

- `C0_canonical_close_to_close`: `position[t] = target[t-1]`; close-to-close return.
- `C1_next_open_executable`: at `open[t]`, use `target[t-1]`; earn observed `open[t] -> open[t+1]` return.
- `C2_extra_1h_latency`: at `open[t]`, use `target[t-2]`; earn the same observed open-to-open return.
- `target[t] = 1` only when `close[t] / close[t-2160] - 1 > 0`.
- Every path starts from cash and pays exactly 5 bps one way on absolute position change.

No spread, slippage, impact, fill probability, queue position, maker fill, leverage, account, or order assumption is included.

## Immutable evidence

Workflow `30347175588`, source head `d7cc15839755484b682d6e9094298b8a32f70230`:

- BTC artifact `8685574446`, ZIP SHA-256 `d36b151d0279e552f0f561403647ca8495febf6bd7c87c0b85cf0e7ad3df6119`;
- ETH artifact `8685572234`, ZIP SHA-256 `e32884abe83663b36bc52ce4f4b3cc60b03bb2f4f2948853134dc6831706a9bb`.

All 13 internal manifest files passed for each market. The reconstructed C0 hourly return matched the canonical benchmark within `9.9964e-17`.

Development window: `2023-07-24 00:00 UTC` through `2026-07-07 23:00 UTC`, 25,920 hours and 12 fixed 2,160-hour folds per market.

Fresh temporal extension: `2026-07-08 00:00 UTC` through `2026-07-28 08:00 UTC`, 489 hours per market, with the real `2026-07-28 09:00 UTC` open available for the final open-to-open return.

## Development results

| Market | Path | Net return | Sharpe | Max DD | Annual turnover | Edge/turnover | Profitable folds |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC | C0 | 111.72% | 0.9174 | -22.67% | 68.94 | 45.11 bps | 5/12 |
| BTC | C1 | 111.53% | 0.9167 | -22.68% | 68.94 | 45.06 bps | 5/12 |
| BTC | C2 | 114.16% | 0.9276 | -23.52% | 68.94 | 45.71 bps | 4/12 |
| ETH | C0 | 67.92% | 0.6170 | -47.31% | 47.31 | 57.86 bps | 6/12 |
| ETH | C1 | 67.94% | 0.6171 | -47.30% | 47.31 | 57.86 bps | 6/12 |
| ETH | C2 | 78.55% | 0.6638 | -45.22% | 47.31 | 62.24 bps | 6/12 |

C1 preserved its full development advantage over unchanged canonical S0:

- BTC C1 minus S0: +67.94 percentage points total return, +0.2798 Sharpe, +11.88 bps edge per turnover;
- ETH C1 minus S0: +51.62 percentage points total return, +0.2747 Sharpe, +45.81 bps edge per turnover.

C1 used the same binary position and turnover path as C0, so its small difference is entirely the observed close-to-close versus next-open return alignment, not a cost-accounting change.

## Fresh temporal extension

The frozen trend target was cash for all 489 extension hours in both markets. C0, C1, and C2 therefore each produced zero exposure, zero turnover, zero modeled fees, and zero net return. Edge per turnover is structurally undefined.

This is valid prospective no-trade evidence but not an exposed-return replication. No parameter may be changed in response.

## Uncertainty

The confirmatory family used 5,000 paired non-circular 168-hour moving-block resamples within each fixed fold, seed `20260728`, preserving every fold-boundary row exactly once and applying Holm correction across eight endpoints.

C1 minus C0 was economically negligible:

- BTC annualized mean delta `-0.0334 pp`, Sharpe delta `-0.00076`;
- ETH annualized mean delta `-0.0018 pp`, Sharpe delta `+0.00010`.

C2 did not show statistically adjusted degradation versus C1. All eight Holm-adjusted p-values were `1.0`; the frozen latency-blocking thresholds were not breached.

DSR and PBO were not calculated because the required global independent-family inventory and CSCV matrix do not exist.

## Causal checks and repair

Passed:

- confirmed, unique, strictly increasing and contiguous 1H bars;
- exact C0 benchmark reconstruction;
- one-bar and two-bar signal timing;
- future-suffix target invariance;
- observed real opens only;
- byte-identical full rerun.

The first artifact attempt represented zero-turnover fresh-period edge and zero-drawdown Calmar as non-finite values. That output was discarded before publication. The final artifact records structurally undefined metrics as JSON `null`, not zero or infinity.

## Research decision

Retain the 2,160H rule only as the fixed development benchmark. It is not latency-sensitive under the frozen criteria, but it still lacks independent-market exposed replication and the fresh extension stayed entirely in cash. The next non-duplicative experiment should test a materially orthogonal information source against C1, not alter the 2,160H lookback or add execution overlays on this consumed window.
