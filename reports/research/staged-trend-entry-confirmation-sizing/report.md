# Staged trend-entry confirmation sizing — terminal report

## Verdict

```text
reject_exact_staged_trend_entry_confirmation_sizing_family
```

One preregistered candidate was tested with no parameter grid. Every newly positive daily 2,160H trend entered immediately at 0.5 exposure; one irreversible top-up to 1.0 was allowed after at least 168 hours only when both return since onset and the latest 168H return were positive. Execution was next-open with exactly 5 bps one way.

## Immutable boundary

- Public confirmed OKX SPOT BTC-USDT and ETH-USDT, evaluated independently.
- Exactly 43,441 contiguous confirmed 1H bars were read from each 43,941-row source; the later suffix was not read or scored.
- Training `[2,880,17,520)`, development OOS `[17,520,43,440)`, full scored `[2,880,43,440)`.
- OOS breadth: 12 contiguous 2,160H folds and four calendar-year segments.
- Uncertainty: 5,000 paired non-circular 168H moving-block resamples, seed `20260730`.
- Candidate count `1`; parameter grid `0`.

## Training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | -28.92% | -0.577 | -45.81% | 17.50 | +0.88% | -156.47 bps |
| BTC-USDT | B1 | -41.29% | -0.840 | -55.92% | 28.00 | +1.40% | -159.81 bps |
| ETH-USDT | CANDIDATE | -31.64% | -0.504 | -46.76% | 15.00 | +0.75% | -189.75 bps |
| ETH-USDT | B1 | -40.59% | -0.584 | -56.95% | 23.00 | +1.15% | -168.77 bps |

## Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | +102.47% | 0.895 | -27.33% | 31.50 | +1.57% | 273.83 bps |
| BTC-USDT | B1 | +119.68% | 0.954 | -26.55% | 45.00 | +2.25% | 212.75 bps |
| BTC-USDT | B0 | +111.64% | 0.917 | -22.68% | 203.00 | +10.15% | 45.31 bps |
| ETH-USDT | CANDIDATE | +80.16% | 0.678 | -43.26% | 19.00 | +0.95% | 453.83 bps |
| ETH-USDT | B1 | +74.52% | 0.646 | -47.77% | 30.00 | +1.50% | 283.58 bps |
| ETH-USDT | B0 | +68.02% | 0.618 | -47.30% | 139.00 | +6.95% | 58.31 bps |

## Full scored sample

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | +43.92% | 0.409 | -45.81% | 49.00 | +2.45% | 120.15 bps |
| BTC-USDT | B1 | +28.97% | 0.332 | -55.92% | 73.00 | +3.65% | 69.85 bps |
| ETH-USDT | CANDIDATE | +23.15% | 0.313 | -46.76% | 34.00 | +1.70% | 169.90 bps |
| ETH-USDT | B1 | +3.68% | 0.233 | -56.95% | 53.00 | +2.65% | 87.28 bps |

## Breadth and uncertainty

| Market | Profitable folds | Profitable years | Concentration | Residual Sharpe | Annualised mean Δ 95% | Sharpe Δ 95% |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 6/12 | 3/4 | 37.02% | -0.587 | [-10.65%, +2.15%] | [-0.257, 0.092] |
| ETH-USDT | 6/12 | 3/4 | 23.85% | 0.058 | [-11.46%, +9.95%] | [-0.220, 0.245] |

## Failure mechanism

### BTC-USDT

- OOS onsets: `22`; top-ups: `9`; half-state hours: `2281`.
- Confirmed regimes: `9` regimes and `1536` half-state hours carried `+36.01%` arithmetic market return. Half sizing therefore cost `+18.00%` before fees.
- Unconfirmed regimes: `14` regimes and `745` half-state hours carried `-15.70%`. Half sizing avoided `+7.85%` before fees.
- Fee saving versus B1: `+0.67%`; total arithmetic candidate-minus-B1 delta: `-9.48%`.
- Candidate OOS versus B1: net `+102.47%` vs `+119.68%`, Sharpe `0.895` vs `0.954`, drawdown `-27.33%` vs `-26.55%`, turnover `31.5` vs `45.0`.
- Mean market return after top-up: 24H `-0.69%`, 168H `+0.42%`, 720H `+6.57%`.

### ETH-USDT

- OOS onsets: `15`; top-ups: `4`; half-state hours: `1992`.
- Confirmed regimes: `4` regimes and `696` half-state hours carried `+50.30%` arithmetic market return. Half sizing therefore cost `+25.15%` before fees.
- Unconfirmed regimes: `11` regimes and `1296` half-state hours carried `-51.50%`. Half sizing avoided `+25.75%` before fees.
- Fee saving versus B1: `+0.55%`; total arithmetic candidate-minus-B1 delta: `+1.15%`.
- Candidate OOS versus B1: net `+80.16%` vs `+74.52%`, Sharpe `0.678` vs `0.646`, drawdown `-43.26%` vs `-47.77%`, turnover `19.0` vs `30.0`.
- Mean market return after top-up: 24H `-0.34%`, 168H `-2.99%`, 720H `+0.62%`.

The architecture correctly reduced exposure in unconfirmed regimes, especially ETH, but the required half-size incubation also removed the first week of return from every confirmed long-duration winner. In BTC that lost early carry dominated the avoided losses. In ETH the two components nearly offset, producing a favourable aggregate point estimate but no breadth or uncertainty support. The confirmation event itself did not predict strong immediate post-top-up returns.

## Evidence repair

The initial diagnostic pooled all half-state exposure. It was repaired without changing the frozen strategy to separate confirmed pre-top-up exposure from permanently unconfirmed regimes and to assert exact hour, carry and arithmetic-PnL attribution identities. Two complete executions after the repair produced byte-identical results. No position, fee, metric, bootstrap draw, gate or verdict changed.

## Acceptance decision

BTC failed benchmark net return, Sharpe, drawdown, fold breadth, residual Sharpe and both uncertainty gates. ETH passed all aggregate point-estimate and efficiency gates but failed fold breadth and both uncertainty gates. The bilateral architecture is rejected. No same-interval change to onset size, minimum age, confirmation inequalities, cadence, fee or market treatment is authorised.

## Remaining blocker and next experiment

**Remaining blocker:** staged confirmation creates the correct monotone turnover geometry, but a fixed half-size incubation penalises the rare long-duration trends before they reveal themselves; the benefit from failed onsets is not bilateral or broad enough.

**Next experiment:** a materially orthogonal own-history-only `trend-renewal drought downgrade` architecture: enter every positive 2,160H trend at full exposure, then permit one irreversible downgrade to 0.5 only when no completed close has renewed the trailing 720H high during the latest 168H and the latest 168H return is negative. This retains full early participation, uses event-time renewal information rather than onset-return confirmation, and remains turnover-neutral versus B1. One candidate, no grid, no market-specific rule.

## Determinism

Terminal result SHA-256: `2f28f861abd61c56b042dc441e1e02f9c9d3ae7ad33a548c2be513a3358bc3f9`
