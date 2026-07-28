# Funding/basis crowding-unwind v2 — short-window falsification

Issue: #541  
Strategy artifact head: `d7aa41480749f6cc9aa0357f6676863868b5b55f`  
Workflow run: `30362230732`  
Immutable artifact: `8689312077` (`sha256:28e25dc4b6537b15f91b593306de630c4e948ff9cd1d993c423aa7a9be280331`)

## Frozen policies

The candidate budget remained exactly two.

- **F0 — funding-only attribution:** go fractionally long only when the settled, interval-normalized 8H-equivalent funding rate is negative; size is `max(0, tanh(-z_funding))`.
- **F1 — strict crowding unwind:** require negative normalized funding, negative mark/index log basis and positive 24H basis recovery simultaneously; size is `max(0, tanh(min(-z_funding, -z_basis, z_recovery)))`.

Both policies use duration-weighted causal medians/MAD within contiguous `(formulaType, method)` episodes. They require at least 30 prior valid settlements and 240 prior interval-hours. Invalid components, regime changes, zero MAD and missed expected settlements fail closed to cash. Fees are exactly 5 bps one-way.

## Public source and availability

The run bound each market from public instrument metadata rather than inferred strings:

| Target | Perpetual | Index |
|---|---|---|
| BTC-USDT | BTC-USDT-SWAP | BTC-USDT |
| ETH-USDT | ETH-USDT-SWAP | ETH-USDT |

Exact fields were `realizedRate`, `fundingTime`, `formulaType`, `method`, inferred settlement interval, completed mark close, completed index close and confirmed spot close.

For settlement time `T`, basis uses the latest completed mark/index 1H candle closing at or before `T`. The feature target is formed only after the first completed spot bar strictly after `T`, and the position is applied to the following close-to-close hour.

The recent public funding endpoint supplied 274 settled observations per market from `2026-04-28 08:00 UTC` through `2026-07-28 08:00 UTC`. Mark and index coverage contained 2,214 contiguous confirmed 1H rows per market; spot coverage contained 4,351 rows. After the frozen warmup, each market had 243 usable settlements.

The bounded archive capability probes returned a successful envelope but an empty `details` list for both instrument families. No archive download URL was available through that request, so the full qualification design—180 warmup days plus at least eight 90-day folds—was not materialized. The executed design was therefore frozen as a falsification-only recent-REST diagnostic before performance inspection.

## Sample

```text
Evaluation          2026-05-08 18:00 UTC — 2026-07-17 17:00 UTC
Hours per market    1,680
Folds               5 × 336H, non-overlapping
Candidates          2
Fee                 5 bps one-way
New canonical OOS   not consumed
```

## Results

| Market | Policy | Net return | Sharpe | Max drawdown | Annual turnover | Edge/turnover | Time long | Profitable folds |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | F0 | -1.26% | -0.199 | -6.39% | 186.18 | -2.30 bps | 23.33% | 1/5 |
| BTC-USDT | F1 | -0.57% | -1.012 | -1.73% | 28.95 | -10.08 bps | 4.29% | 1/5 |
| ETH-USDT | F0 | -1.10% | -0.061 | -10.11% | 196.62 | -0.88 bps | 25.24% | 2/5 |
| ETH-USDT | F1 | +2.34% | +1.713 | -1.94% | 55.85 | +22.03 bps | 6.67% | 2/5 |

F1 emitted 10 positive BTC settlement targets and 16 positive ETH targets. The mechanism did not replicate across markets. BTC F1 had negative gross and net return, negative Sharpe, negative edge per turnover and worse Sharpe/edge than F0. Its only positive fold supplied 100% of positive-fold return.

The fixed 2,160H simple-trend benchmark lost heavily during this short 2026 interval, so positive residual Sharpe versus trend is not promotion evidence.

### Tail behavior

```text
BTC F0 worst 24H / 168H   -4.21% / -3.81%
BTC F1 worst 24H / 168H   -1.09% / -1.69%
ETH F0 worst 24H / 168H   -5.40% / -5.40%
ETH F1 worst 24H / 168H   -1.41% / -1.10%
```

F1 reduced tail exposure by spending most hours in cash, but BTC did not earn a positive premium for that protection.

## Adjusted uncertainty

Inference used 5,000 paired, non-circular 168H moving-block resamples within each frozen fold, preserving the boundary row once, with seed `20260728`. The confirmatory statistics were the worst-market F1-minus-F0 Sharpe and edge-per-turnover differences.

```text
Worst-market Sharpe delta      -0.8132
One-sided 95% lower bound      -3.6020
Holm-adjusted p                 1.0000

Worst-market edge delta         -7.7726 bps
One-sided 95% lower bound      -36.4551 bps
Holm-adjusted p                 1.0000
```

## Causal and reconstruction checks

Both markets passed:

- exact public HTTPS origin and unauthenticated requests;
- persisted raw response bytes plus SHA-256 manifest;
- confirmed, unique, increasing and contiguous 1H bars;
- shuffled, gapped and duplicated-bar fail-closed attacks;
- future-suffix prefix replay for F0/F1 target and position state;
- one-bar post-decision execution and symmetric 5 bps fee accounting.

### Repair after inspection

The first successful workflow artifact recorded GitHub's pull-request merge SHA rather than the exact checked-out strategy head. This did not alter metrics, but it weakened artifact identity. The workflow was repaired to inject the verified checked-out head at process launch and fail unless the emitted `generated_from_commit` matches it. The unchanged experiment was rerun. Every strategy metric, screen, bootstrap result and verdict was identical; the corrected artifact now binds to `d7aa41480749f6cc9aa0357f6676863868b5b55f`.

## Verdict

```text
rejected_by_predeclared_short_window_diagnostic
```

The exact F0/F1 family is rejected. ETH's isolated positive result cannot override a deterministic BTC failure under an identical per-instrument rule. The family must not be rescued on the same evidence by changing the funding threshold, basis sign, recovery horizon, normalization, warmup, holding rule or position transform.

The next non-duplicative derivatives experiment should use a materially different mechanism—preferably point-in-time open-interest-adjusted price response or a liquidation-pressure state—after its own source and availability contract is frozen.