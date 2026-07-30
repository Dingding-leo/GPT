# Expanding base-exit recross-hazard sleeve — terminal report

```text
family          expanding-base-exit-recross-hazard-sleeve-1h-v1
candidate count 1
parameter grid  0
fee             exactly 5 bps one way
verdict         reject_exact_expanding_base_exit_recross_hazard_sleeve_family
```

## Frozen strategy

At each instrument’s first completed daily `00:00 UTC` transition from a positive to a non-positive 2,160H endpoint trend, the candidate estimated the probability of a positive daily base recross within 168H. The expanding model used only earlier completed exit episodes from the same instrument.

Frozen exit features:

```text
margin_depth = -log(close_t / close_(t-2160H))
return_24h   =  log(close_t / close_(t-24H))
negative_age =  log1p(consecutive hourly non-positive base observations) / log(25)
```

The features were standardized using only prior completed episodes. A deterministic ridge-logistic model used `lambda=1`, a fixed neutral two-observation prior, at most 100 IRLS iterations, and a strict `p > 0.5` decision. A selected exit retained `0.5` exposure until daily base recross or the exact 168H expiry; all other non-positive states held cash. Positive base states always held `1.0`. No cross-market pooling, fitted threshold, grid, leverage, shorting, exogenous input, or market-specific rule was used.

## Immutable data and evaluation

- Public confirmed OKX SPOT BTC-USDT and ETH-USDT 1H candles, evaluated independently.
- Canonical workflow run `30567744552`; BTC artifact `8769605568`; ETH artifact `8769619607`.
- First 43,441 contiguous confirmed rows only, spanning 24 July 2021 through 8 July 2026 UTC.
- Training `[2,880,17,520)`; development OOS `[17,520,43,440)`; full `[2,880,43,440)`.
- Twelve contiguous 2,160H OOS folds and four calendar years.
- 5,000 paired non-circular 168H moving-block resamples, seed `20260731`.
- Completed-bar decisions, next-hour-open execution, open-to-open returns, and `0.0005 × abs(exposure change)` fees.
- Full/prefix hashes, confirmed chronology, future-suffix invariance, episode chronology, next-open timing, fee identity, sleeve duration, and candidate-minus-B1 arithmetic decomposition passed.

## Training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC | CANDIDATE | -43.12% | -0.877 | -57.24% | 23.0 | +1.15% | -206.86 |
| BTC | B1 | -41.29% | -0.840 | -55.92% | 28.0 | +1.40% | -159.81 |
| BTC | B0 | -41.02% | -0.831 | -55.56% | 138.0 | +6.90% | -32.09 |
| ETH | CANDIDATE | -35.31% | -0.453 | -56.95% | 18.5 | +0.92% | -163.33 |
| ETH | B1 | -40.59% | -0.584 | -56.95% | 23.0 | +1.15% | -168.77 |
| ETH | B0 | -46.84% | -0.744 | -57.75% | 88.0 | +4.40% | -56.53 |

BTC reduced turnover but worsened return, Sharpe, drawdown, and edge per turnover versus B1. ETH improved training return and Sharpe while tying B1 drawdown, but both candidates remained negative.

## Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC | CANDIDATE | +105.54% | 0.873 | -30.90% | 28.0 | +1.40% | 321.61 |
| BTC | B1 | +119.68% | 0.954 | -26.55% | 45.0 | +2.25% | 212.75 |
| BTC | B0 | +111.64% | 0.917 | -22.68% | 203.0 | +10.15% | 45.31 |
| ETH | CANDIDATE | +64.29% | 0.599 | -47.51% | 23.5 | +1.18% | 337.77 |
| ETH | B1 | +74.52% | 0.646 | -47.77% | 30.0 | +1.50% | 283.58 |
| ETH | B0 | +68.02% | 0.618 | -47.30% | 139.0 | +6.95% | 58.31 |

BTC sacrificed 14.14 percentage points of compounded return, reduced Sharpe by `0.081`, and worsened drawdown by 4.35 points. Turnover fell by 17 units and edge per turnover rose, but the saved fees did not offset adverse bridge carry.

ETH sacrificed 10.22 percentage points of compounded return and reduced Sharpe by `0.047`. Drawdown improved by 0.26 point, turnover fell by 6.5 units, and edge per turnover rose, but benchmark-relative return and Sharpe failed.

## Full scored sample

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC | CANDIDATE | +16.92% | 0.270 | -57.24% | 51.0 | +2.55% | 83.28 |
| BTC | B1 | +28.97% | 0.332 | -55.92% | 73.0 | +3.65% | 69.85 |
| BTC | B0 | +24.82% | 0.310 | -55.56% | 341.0 | +17.05% | 13.98 |
| ETH | CANDIDATE | +6.29% | 0.246 | -56.95% | 42.0 | +2.10% | 117.05 |
| ETH | B1 | +3.68% | 0.233 | -56.95% | 53.0 | +2.65% | 87.28 |
| ETH | B0 | -10.68% | 0.158 | -57.75% | 227.0 | +11.35% | 13.79 |

## Breadth and uncertainty

| Market | Profitable folds | Improved folds | Profitable years | Improved years | Concentration | Residual Sharpe | Mean Δ 95% | Sharpe Δ 95% |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC | 4/12 | 4/12 | 3/4 | 1/4 | 34.72% | -0.238 | [-8.70%, +4.46%] | [-0.281, +0.103] |
| ETH | 6/12 | 3/12 | 3/4 | 1/4 | 23.48% | -0.404 | [-7.31%, +2.27%] | [-0.171, +0.049] |

Neither market reached seven profitable folds. Both residual Sharpes were negative, and every dependence-aware lower confidence bound remained below zero.

## Failure mechanism

### BTC — the fitted features added no selection beyond the expanding prior

```text
OOS exits                              23
Selected exits                         23
Decision disagreements vs base rate    0
Model Brier                            0.1979
Expanding-base-rate Brier               0.1917
Extra full-equivalent exposure          1092.0H
Full market carry during extra exposure -13.08%
Timing contribution                     -6.54%
Fee contribution                        +0.85%
Arithmetic candidate-minus-B1           -5.69%
Turnover saved                          17.0
```

The expanding recross base rate exceeded one half throughout OOS, and the feature model selected every BTC exit. It made zero OOS decisions different from the intercept-only expanding prior and had slightly worse Brier loss. The architecture therefore collapsed to a broad half bridge rather than an informative selector.

The largest losses came from the 168H sleeves beginning 3 June 2026 (`-7.32%` market carry), 25 February 2025 (`-5.78%`), 22 June 2024 (`-5.13%`), and 11 October 2025 (`-4.92%`). A recross label was also economically misaligned: the 10 June 2024 exit recrossed within 120H but lost `-4.83%` before recross.

### ETH — better recross classification, wrong economic target

```text
OOS exits                              15
Selected / rejected exits               9 / 6
Decision disagreements vs base rate    7
Model Brier                            0.2350
Expanding-base-rate Brier               0.2652
Extra full-equivalent exposure          396.5H
Full market carry during extra exposure -12.05%
Timing contribution                     -6.02%
Fee contribution                        +0.33%
Arithmetic candidate-minus-B1           -5.70%
Turnover saved                          6.5
```

The ETH model made seven decisions different from the expanding base-rate classifier and improved Brier loss by `0.0302`, so the features contained some event information. That information did not map to profitable bridge carry. Three high-confidence selected exits expired after severe losses: 5 June 2024 (`p=0.765`, `-8.83%` market carry), 17 August 2023 (`p=0.898`, `-6.15%`), and 4 July 2024 (`p=0.847`, `-5.81%`).

The central falsification is target misalignment: “recross within 168H” is not equivalent to “positive return while waiting for recross.” A sleeve can correctly anticipate a later base recross yet absorb a large adverse path first.

### Diagnostic repair

The initial aggregate diagnostic could not distinguish feature information from the expanding class prior and did not expose event-level carry. The terminal reproducer adds a non-selectable expanding-intercept shadow, Brier comparison, exact decision disagreements, and per-sleeve market/timing attribution. No feature, probability, selection, exposure, fee, performance metric, bootstrap draw, gate, or verdict changed. Two complete executions produced byte-identical protocol and result files.

```text
protocol SHA-256     85be192610b5dd647d2929c3b2158e0d2b7d79c3e60d8cdc30907e5b5938efe2
compact result SHA-256 3ddb71f6f6316aaa8f55dd19dca2173880d93313f47002d2e7078d4ed8e56404
full result SHA-256  9a6f7625291144ff18a36c54db7e308498f7c292cb65994285de6f33ebe40e12
```

## Verdict

```text
reject_exact_expanding_base_exit_recross_hazard_sleeve_family
```

BTC failed OOS return, Sharpe, drawdown, profitable-fold breadth, residual Sharpe, and both uncertainty gates. ETH failed OOS return, Sharpe, profitable-fold breadth, residual Sharpe, and both uncertainty gates.

No same-interval estimator, penalty, feature transform, probability threshold, sleeve fraction, horizon, cadence, fee, market subset, or market-specific rescue is authorised. There is no G1, paper, or live-trading nomination.

**Remaining blocker:** the event label must be economically aligned with the exposure path. Recross occurrence is too weak a target because the waiting-period return can be strongly negative even when recross happens on schedule. In BTC the fixed features also failed to add any decision information beyond the expanding recross prior.

**Next strategy experiment:** after a rejected-family de-duplication audit, preregister one payoff-aligned expanding exit selector on the already-frozen SOL/XRP/LTC/DOGE replication cohort. For each instrument independently, train only on its prior completed exit episodes and label the exact 168H half-sleeve arithmetic contribution net of the turnover difference versus B1, rather than the recross event. Use one fixed regularized model and one sleeve policy across all four markets, no BTC/ETH refit, no market filtering, one candidate, no grid, and unchanged 5-bps breadth and moving-block gates. This tests target innovation on a distinct cohort instead of rescuing the consumed BTC/ETH interval.
