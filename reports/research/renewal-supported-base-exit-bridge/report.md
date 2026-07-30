# Renewal-supported base-exit bridge — terminal report

## Verdict

```text
reject_exact_renewal_supported_base_exit_bridge_family
```

One preregistered own-history-only candidate was tested with no parameter grid. The candidate held full exposure throughout every positive daily 2,160H endpoint trend. At the first non-positive base decision, it retained a 0.5 sleeve for exactly 168H only when at least one strict causal trailing-720H closing-high renewal occurred during the preceding 168H. It restored full exposure if the base trend became positive during the bridge, otherwise exited after the fixed bridge. Execution was at the next hourly open with exactly 5 bps one way.

## Immutable boundary

- Public confirmed OKX SPOT BTC-USDT and ETH-USDT, evaluated independently.
- Exactly 43,441 contiguous confirmed 1H bars from 24 July 2021 through 8 July 2026 UTC were read from each 43,941-row source.
- Training `[2,880,17,520)`, development OOS `[17,520,43,440)`, full scored `[2,880,43,440)`.
- The later suffix `[43,440,end)` was unread and unscored.
- OOS breadth: 12 contiguous 2,160H folds and four calendar-year segments.
- Uncertainty: 5,000 paired non-circular 168H moving-block resamples, seed `20260730`.
- Candidate count `1`; parameter-grid count `0`.

## Training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | -39.61% | -0.784 | -55.42% | 25.0 | +1.25% | -167.50 bps |
| BTC-USDT | B1 | -41.29% | -0.840 | -55.92% | 28.0 | +1.40% | -159.81 bps |
| BTC-USDT | B0 | -41.02% | -0.831 | -55.56% | 138.0 | +6.90% | -32.09 bps |
| ETH-USDT | CANDIDATE | -37.46% | -0.504 | -56.95% | 19.0 | +0.95% | -176.91 bps |
| ETH-USDT | B1 | -40.59% | -0.584 | -56.95% | 23.0 | +1.15% | -168.77 bps |
| ETH-USDT | B0 | -46.84% | -0.744 | -57.75% | 88.0 | +4.40% | -56.53 bps |

The bridge modestly improved compounded training loss in both markets and reduced turnover, but both candidates remained negative. BTC edge per turnover was slightly worse than B1 despite the lower loss; ETH Sharpe improved while drawdown was unchanged.

## Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | +111.75% | 0.912 | -28.37% | 42.0 | +2.10% | 219.97 bps |
| BTC-USDT | B0 | +111.64% | 0.917 | -22.68% | 203.0 | +10.15% | 45.31 bps |
| BTC-USDT | B1 | +119.68% | 0.954 | -26.55% | 45.0 | +2.25% | 212.75 bps |
| ETH-USDT | CANDIDATE | +78.91% | 0.664 | -47.77% | 28.0 | +1.40% | 312.75 bps |
| ETH-USDT | B0 | +68.02% | 0.618 | -47.30% | 139.0 | +6.95% | 58.31 bps |
| ETH-USDT | B1 | +74.52% | 0.646 | -47.77% | 30.0 | +1.50% | 283.58 bps |

BTC reduced turnover from 45.0 to 42.0 and improved edge per turnover, but lost 7.94 percentage points of compounded return, reduced Sharpe by 0.042 and worsened drawdown by 1.82 points versus B1.

ETH improved every benchmark-relative point estimate except drawdown, which was equal within numerical tolerance: return improved by 4.39 points, Sharpe by 0.019, turnover fell from 30.0 to 28.0 and edge per turnover rose by 29.16 bps.

## Full scored sample

| Market | Policy | Net | Sharpe | Max DD | Turnover | Edge/turn |
|---|---|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | +27.88% | 0.326 | -55.42% | 67.0 | 75.39 bps |
| BTC-USDT | B1 | +28.97% | 0.332 | -55.92% | 73.0 | 69.85 bps |
| ETH-USDT | CANDIDATE | +11.88% | 0.272 | -56.95% | 47.0 | 114.80 bps |
| ETH-USDT | B1 | +3.68% | 0.233 | -56.95% | 53.0 | 87.28 bps |

BTC remained positive over the full scored sample but slightly underperformed B1. ETH improved full-sample return, Sharpe, turnover and edge per turnover.

## Breadth and uncertainty

| Market | Profitable folds | Profitable years | Positive-fold concentration | Residual Sharpe | Annualised mean delta 95% | Sharpe delta 95% |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 5/12 | 3/4 | 34.37% | -0.239 | [-5.32%, +2.92%] | [-0.168, +0.076] |
| ETH-USDT | 6/12 | 3/4 | 22.27% | 1.194 | [+0.00%, +2.33%] | [+0.000, +0.053] |

Neither market reached the required 7/12 profitable folds. BTC residual Sharpe was negative and both uncertainty intervals crossed zero. ETH residual Sharpe was strongly positive, but both lower confidence bounds were exactly zero rather than strictly positive because the beneficial bridge state occurred in only two short episodes.

## Failure mechanism

### BTC-USDT

```text
Bridge starts                         4
Restorations / expiries               3 / 1
Bridge hours                          480
Full-equivalent hours added           240.0
Full market carry during bridges      -7.00%
Timing contribution                   -3.50%
Incremental fees vs B1                -0.15%
Arithmetic candidate-minus-B1         -3.35%
```

BTC generated four OOS bridges. Three restored before expiry and one expired. Two bridge intervals were positive and two were negative; the largest restored episode lost 4.83% over 120H and the expiry episode lost 4.92% over 168H. Fee savings recovered only 0.15 percentage points, so recent renewal did not reliably identify harmless base interruptions.

### ETH-USDT

```text
Bridge starts                         2
Restorations / expiries               2 / 0
Bridge hours                          72
Full-equivalent hours added           36.0
Full market carry during bridges      +4.79%
Timing contribution                   +2.39%
Incremental fees vs B1                -0.10%
Arithmetic candidate-minus-B1         +2.49%
```

ETH generated only two OOS bridges, both restoring rapidly after 48H and 24H. Their full-market returns were +3.55% and +1.23%, producing a positive timing contribution plus fee savings. The economics were favourable but entirely concentrated in two events, insufficient for fold breadth or strictly positive dependence-aware lower bounds.

## Evidence repair

The initial acceptance diagnostic treated an ETH drawdown difference of approximately `3e-15` as a failure even though the candidate and B1 drawdowns were economically and numerically identical. The terminal reproducer applies a fixed `1e-12` equality tolerance to the frozen no-worse drawdown gate. No position, fee, return, bootstrap draw, substantive acceptance conclusion or verdict changed.

Two complete executions produced byte-identical terminal results:

```text
result.json SHA-256
c157ef52c141d418da2ef41fefe2d7ade28586e77c58d9457e78fb9032ea63bf
```

## Verdict

```text
reject_exact_renewal_supported_base_exit_bridge_family
```

BTC failed return, Sharpe, drawdown, fold breadth, residual Sharpe and both uncertainty gates. ETH passed all point-estimate efficiency gates but failed fold breadth and both strict uncertainty lower-bound gates because only two short bridge events occurred.

No same-interval modification to the renewal horizon, bridge lookback or duration, half-sleeve size, strict inequality, trend horizon, cadence, fee or market-specific treatment is authorised. There is no G1 nomination, paper promotion or live-trading authorisation.

**Remaining blocker:** recent high renewal is a useful ETH recross indicator but does not transport to BTC and is too event-sparse. A bridge selector must distinguish mechanical base exits from fresh price deterioration without vetoing positive regimes or adding turnover.

**Next strategy experiment:** one own-history-only `base-exit margin-source bridge`. Hold every positive 2,160H regime at full exposure. At the first non-positive base decision, retain a fixed 0.5 sleeve for 168H only when the exit is mechanically driven by a positive 24H lag-endpoint leg entering the comparison while the current 24H close leg is non-negative; otherwise exit directly. Restore full exposure on base recross, one candidate, no grid and unchanged bilateral gates.
