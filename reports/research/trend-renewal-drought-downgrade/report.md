# Trend-renewal drought downgrade — terminal report

## Verdict

```text
reject_exact_trend_renewal_drought_downgrade_family
```

One preregistered own-history-only candidate was tested with no parameter grid. Every newly positive daily 2,160H endpoint trend entered at full exposure. After at least 168H, the first daily decision with no hourly close renewing its causal trailing 720H closing high during the latest 168H and a negative latest-168H return irreversibly downgraded exposure to `0.5` until the base-trend exit. Execution was at the next hourly open with exactly 5 bps one way.

## Immutable boundary

- Public confirmed OKX SPOT BTC-USDT and ETH-USDT, evaluated independently.
- Exactly 43,441 contiguous confirmed 1H bars from 24 July 2021 through 8 July 2026 UTC were read from each 43,941-row source.
- Training `[2,880,17,520)`, development OOS `[17,520,43,440)`, full scored `[2,880,43,440)`.
- The suffix `[43,440,end)` was unread and unscored.
- OOS breadth: 12 contiguous 2,160H folds and four calendar-year segments.
- Uncertainty: 5,000 paired non-circular 168H moving-block resamples, seed `20260730`.
- Candidate count `1`; parameter-grid count `0`.

## Training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | -36.15% | -1.081 | -47.88% | 27.50 | +1.37% | -147.74 bps |
| BTC-USDT | B1 | -41.29% | -0.840 | -55.92% | 28.00 | +1.40% | -159.81 bps |
| BTC-USDT | B0 | -41.02% | -0.831 | -55.56% | 138.00 | +6.90% | -32.09 bps |
| ETH-USDT | Candidate | -29.20% | -0.678 | -43.43% | 22.50 | +1.12% | -129.00 bps |
| ETH-USDT | B1 | -40.59% | -0.584 | -56.95% | 23.00 | +1.15% | -168.77 bps |
| ETH-USDT | B0 | -46.84% | -0.744 | -57.75% | 88.00 | +4.40% | -56.53 bps |

The candidate improved compounded loss and drawdown in both markets, but BTC Sharpe deteriorated and both candidates remained negative. Training turnover was marginally below B1 because a half-position crossed the training boundary.

## Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +57.16% | 0.832 | -17.74% | 45.00 | +2.25% | 114.97 bps |
| BTC-USDT | B1 | +119.68% | 0.954 | -26.55% | 45.00 | +2.25% | 212.75 bps |
| BTC-USDT | B0 | +111.64% | 0.917 | -22.68% | 203.00 | +10.15% | 45.31 bps |
| ETH-USDT | Candidate | +32.52% | 0.495 | -29.88% | 30.00 | +1.50% | 127.39 bps |
| ETH-USDT | B1 | +74.52% | 0.646 | -47.77% | 30.00 | +1.50% | 283.58 bps |
| ETH-USDT | B0 | +68.02% | 0.618 | -47.30% | 139.00 | +6.95% | 58.31 bps |

BTC drawdown improved from -26.55% to -17.74%, but compounded return fell by 62.52 percentage points, Sharpe fell by 0.121, and edge per turnover nearly halved. Turnover and fees were exactly equal to B1.

ETH drawdown improved by 17.89 percentage points, but return fell by 42.00 points and Sharpe by 0.150. Turnover and fees again matched B1 exactly.

## Full scored sample

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +0.34% | 0.111 | -47.88% | 72.50 | +3.62% | 15.32 bps |
| BTC-USDT | B1 | +28.97% | 0.332 | -55.92% | 73.00 | +3.65% | 69.85 bps |
| BTC-USDT | B0 | +24.82% | 0.310 | -55.56% | 341.00 | +17.05% | 13.98 bps |
| ETH-USDT | Candidate | -6.17% | 0.077 | -43.43% | 52.50 | +2.63% | 17.51 bps |
| ETH-USDT | B1 | +3.68% | 0.233 | -56.95% | 53.00 | +2.65% | 87.28 bps |
| ETH-USDT | B0 | -10.68% | 0.158 | -57.75% | 227.00 | +11.35% | 13.79 bps |

BTC remained barely positive over the full scored sample. ETH became negative. Training-period drawdown reduction could not compensate for the OOS carry removed after the irreversible downgrade.

## Breadth and uncertainty

| Market | Profitable folds | Profitable years | Positive-fold concentration | Residual Sharpe | Annualised mean delta 95% | Sharpe delta 95% |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 5/12 | 3/4 | 33.23% | -0.967 | [-33.18%, +1.94%] | [-0.424, 0.209] |
| ETH-USDT | 6/12 | 3/4 | 32.37% | -0.760 | [-40.56%, +7.24%] | [-0.492, 0.243] |

Neither market reached the required 7/12 profitable folds. Both residual Sharpes were strongly negative and all dependence-aware lower confidence bounds were below zero.

## Failure mechanism

### BTC-USDT

```text
OOS actionable downgrades                 7
Eligible drought decisions                165
Repeated eligible decisions after cut     158
Half-state hours                           11,376
Full-equivalent hours removed              5,688.0
Half-state market carry                    +88.00%
Arithmetic candidate-minus-B1 delta        -44.00%
Incremental fees                           +0.00%
```

Before the first subsequent trailing-high renewal, 1,285 half-state hours carried -8.32%; the drought warning therefore identified some initial weakness. After a new high causally demonstrated renewed strength, the irreversible half state persisted for 10,091 hours carrying +96.32%. About 88.70% of reduced exposure occurred after renewal. The mean post-trigger return was +1.20% over 24H, +2.59% over 168H and +6.54% over 720H.

### ETH-USDT

```text
OOS actionable downgrades                 5
Eligible drought decisions                177
Repeated eligible decisions after cut     172
Half-state hours                           10,824
Full-equivalent hours removed              5,412.0
Half-state market carry                    +93.72%
Arithmetic candidate-minus-B1 delta        -46.86%
Incremental fees                           -0.00%
```

ETH failed more directly. Even the 1,050 pre-renewal half-state hours carried +17.74%; after renewal, 9,774 hours carried another +75.98%. The trigger had a negative mean next-24H return of -0.55%, but the fixed irreversible state outlived that short warning horizon and removed positive slow-trend carry.

## Evidence repair

The initial diagnostic pooled all post-downgrade exposure. It was repaired without changing the frozen rule to locate the first subsequent causal hourly 720H-high renewal in each episode and partition half-state hours and carry before versus after that renewal. Exact hour and arithmetic-carry identities are asserted. The repair showed that most reduced exposure occurred after renewed strength: 88.70% of BTC half-state hours and 90.30% of ETH half-state hours.

Two complete post-repair executions produced byte-identical result files. No feature, position, fee, performance metric, bootstrap draw, acceptance gate or verdict changed.

## Acceptance decision

BTC failed benchmark return, Sharpe, edge per turnover, fold breadth, residual Sharpe and both uncertainty gates. ETH failed those gates and also failed positive full-scored return. Drawdown and turnover improvements cannot rescue the frozen bilateral scorecard.

```text
reject_exact_trend_renewal_drought_downgrade_family
```

No same-interval change to the 720H high, 168H drought/return window, age gate, inequalities, half exposure, irreversible state, cadence, fee or market-specific treatment is authorised. There is no G1 nomination, paper promotion or live-trading authorisation.

## Remaining blocker and next strategy experiment

**Remaining blocker:** drought is a short-lived warning, while the irreversible downgrade is a long-duration state. BTC showed modest negative carry before renewal, but both markets generated most of their subsequent positive trend carry after a new causal high. ETH did not show reliable negative carry even before renewal.

**Next experiment:** one materially distinct own-history-only `renewal-supported base-exit bridge`. Keep full exposure throughout every positive 2,160H trend. When the base trend first becomes non-positive, retain a 0.5 sleeve for exactly 168H only if at least one causal 720H closing-high renewal occurred in the preceding 168H; restore full exposure if the base trend turns positive during the bridge, otherwise exit after the bridge. One candidate, no grid, no leverage, and complete-regime turnover no greater than B1.
