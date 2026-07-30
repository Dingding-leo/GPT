# Endpoint-margin acceleration checkpoint — terminal report

```text
family          endpoint-margin-acceleration-checkpoint-1h-v1
candidate count 1
parameter grid  0
fee             exactly 5 bps one way
verdict         reject_exact_endpoint_margin_acceleration_checkpoint_family
```

## Frozen strategy

At each completed daily `00:00 UTC` decision, each instrument independently computed:

```text
m_t = log(close_t / close_(t-2160H))
latest_change    = m_t - m_(t-168H)
preceding_change = m_(t-168H) - m_(t-336H)
```

Every newly positive 2,160H endpoint trend entered at full exposure. During an already-positive regime, the first decision with both changes negative and `latest_change < preceding_change` irreversibly reduced exposure from `1.0` to `0.5` until the base trend became non-positive. The rule had no fitted threshold, no parameter grid, no exogenous input, and no market-specific treatment. Execution was at the next hourly open with exactly 5 bps charged per absolute exposure change.

## Immutable data and evaluation

- Public confirmed OKX SPOT BTC-USDT and ETH-USDT 1H candles, evaluated independently.
- Exact-head successful canonical workflow run `30567744552`; BTC artifact `8769605568`, ETH artifact `8769619607`.
- First 43,441 confirmed contiguous rows only; training `[2,880,17,520)`, development OOS `[17,520,43,440)`, full `[2,880,43,440)`.
- Twelve contiguous 2,160H OOS folds and four calendar years.
- 5,000 paired non-circular 168H moving-block resamples, seed `20260731`.

## Training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | -35.07% | -1.039 | -47.07% | 27.5 | 1.38% | -141.71 bps |
| BTC-USDT | B1 | -41.29% | -0.840 | -55.92% | 28.0 | 1.40% | -159.81 bps |
| BTC-USDT | B0 | -41.02% | -0.831 | -55.56% | 138.0 | 6.90% | -32.09 bps |
| ETH-USDT | Candidate | -30.77% | -0.587 | -48.69% | 22.5 | 1.12% | -130.24 bps |
| ETH-USDT | B1 | -40.59% | -0.584 | -56.95% | 23.0 | 1.15% | -168.77 bps |
| ETH-USDT | B0 | -46.84% | -0.744 | -57.75% | 88.0 | 4.40% | -56.53 bps |

## Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +82.68% | 0.946 | -18.64% | 45.0 | 2.25% | 154.10 bps |
| BTC-USDT | B1 | +119.68% | 0.954 | -26.55% | 45.0 | 2.25% | 212.75 bps |
| BTC-USDT | B0 | +111.64% | 0.917 | -22.68% | 203.0 | 10.15% | 45.31 bps |
| ETH-USDT | Candidate | +34.88% | 0.485 | -35.71% | 30.0 | 1.50% | 145.48 bps |
| ETH-USDT | B1 | +74.52% | 0.646 | -47.77% | 30.0 | 1.50% | 283.58 bps |
| ETH-USDT | B0 | +68.02% | 0.618 | -47.30% | 139.0 | 6.95% | 58.31 bps |

## Full scored

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +18.61% | 0.274 | -47.17% | 72.5 | 3.62% | 41.90 bps |
| BTC-USDT | B1 | +28.97% | 0.332 | -55.92% | 73.0 | 3.65% | 69.85 bps |
| BTC-USDT | B0 | +24.82% | 0.310 | -55.56% | 341.0 | 17.05% | 13.98 bps |
| ETH-USDT | Candidate | -6.62% | 0.102 | -48.69% | 52.5 | 2.62% | 27.31 bps |
| ETH-USDT | B1 | +3.68% | 0.233 | -56.95% | 53.0 | 2.65% | 87.28 bps |
| ETH-USDT | B0 | -10.68% | 0.158 | -57.75% | 227.0 | 11.35% | 13.79 bps |

## Breadth and uncertainty

| Market | Profitable folds | Profitable years | Improved folds/years | Concentration | Residual Sharpe | Mean Δ 95% | Sharpe Δ 95% |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 5/12 | 3/4 | 5/12; 2/4 | 35.73% | -0.667 | [-23.38%, +6.09%] | [-0.379, +0.360] |
| ETH-USDT | 6/12 | 2/4 | 4/12; 1/4 | 34.90% | -0.746 | [-35.95%, +8.87%] | [-0.575, +0.220] |

Neither market reached seven profitable folds. Both residual Sharpes were negative, and every dependence-aware lower confidence bound was below zero. ETH also failed the three-profitable-year and positive-full-sample gates.

## Failure mechanism

### BTC-USDT

```text
OOS downgrade events                 7
Half-state hours                     8,520
Full-equivalent exposure removed     4,260.0H
Market arithmetic return in state    +52.79%
Timing contribution versus B1        -26.39%
Fee contribution versus B1           -0.000%
Arithmetic candidate-minus-B1        -26.39%
```

- Mean next-24H return: `-0.15%`; positive share `42.9%`.
- Mean next-168H return: `+1.08%`; positive share `71.4%`.
- Mean next-720H return: `+8.92%`; positive share `71.4%`.

The largest failure was the December 2023 downgrade, which remained half-sized for 4,008 hours while the market compounded `+58.76%`. The trigger had slightly negative mean next-24H return, but positive mean next-168H and next-720H returns. Accelerating endpoint-margin decay therefore remained a short-horizon weakness marker rather than a durable BTC trend-failure state.

### ETH-USDT

```text
OOS downgrade events                 4
Half-state hours                     8,304
Full-equivalent exposure removed     4,152.0H
Market arithmetic return in state    +82.87%
Timing contribution versus B1        -41.43%
Fee contribution versus B1           -0.000%
Arithmetic candidate-minus-B1        -41.43%
```

- Mean next-24H return: `+1.92%`; positive share `50.0%`.
- Mean next-168H return: `+4.95%`; positive share `50.0%`.
- Mean next-720H return: `+11.14%`; positive share `50.0%`.

The January 2024 and June 2025 downgrades remained half-sized for 3,648 and 3,240 hours while the market compounded `+68.43%` and `+44.59%`. Mean post-trigger returns were positive at 24H, 168H, and 720H. The state removed the principal ETH trend continuations and drove the full scored candidate negative.

### Diagnostic repair

The first implementation attempted to assign a next-open position beyond the available return boundary and failed before producing any performance output. The execution loop was repaired to stop at the last decision with a realizable next-open return. After inspecting the terminal events, the event timestamp diagnostic was also corrected from the following candle timestamp to the actual next-open execution timestamp. Neither repair changed the frozen signal, any realizable position, return, fee, bootstrap draw, gate, or verdict.

Two complete terminal executions produced byte-identical result files:

```text
result.json SHA-256  aea7756c762ad93f92dec68bbb545f95ae11cb932ebbfd244a38c06cc77ab225
canonical payload    3310bbac94380eb02950eb2456bbcd2e2b17cf730db807b98ad3f9af8fd9821e
```

## Verdict

```text
reject_exact_endpoint_margin_acceleration_checkpoint_family
```

BTC failed OOS return, Sharpe, edge per turnover, profitable-fold breadth, residual Sharpe, and both uncertainty gates. ETH failed OOS return, Sharpe, edge per turnover, profitable-fold breadth, profitable-year breadth, residual Sharpe, both uncertainty gates, and positive full-scored return.

No same-interval change to the 168H blocks, acceleration inequality, 2,160H margin, exposure fraction, irreversible state, cadence, fee, or market-specific treatment is authorised. There is no research-gate nomination, paper promotion, or live-trading authorisation.

## Remaining blocker and next experiment

The bottleneck is holding-horizon mismatch: endpoint-margin deterioration can coincide with brief weakness, but an irreversible half state persists through the rare long-duration regimes that generate most benchmark return. The next experiment should test a fixed-duration, turnover-bounded checkpoint rather than another permanent state: one 168H half-exposure window after the same trigger, with automatic full restoration when the base remains positive and at most one checkpoint per regime. That is a distinct temporal-horizon hypothesis and must be preregistered on a fresh interval before evaluation.
