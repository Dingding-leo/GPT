# BOCPD run-length posterior long/cash experiment

```text
family          bocpd-runlength-hysteresis-1h-v1
candidate count 1
parameter grid  0
markets         BTC-USDT and ETH-USDT independently
bar             immutable public confirmed OKX SPOT 1H
fee             exactly 5 bps one way
verdict         reject_bocpd_runlength_hysteresis_architecture_v1
```

## Immutable data and sample

| Field | Frozen value |
|---|---|
| BTC source | artifact `8769605568`; CSV SHA-256 `40c7ba3dbf64b8b31c634a79e1a2d5e2fa9d60b024c1fd62848d37ed967c13a0` |
| ETH source | artifact `8769619607`; CSV SHA-256 `0164a5cc1730f70ad9817980d67d6350cf71013cdb759c1a153a66890127d6f8` |
| Frozen rows | first 43,441 confirmed contiguous hourly bars |
| Training | rows `[17,520,30,480)`, 24 July 2023–14 January 2025 UTC |
| Development OOS | rows `[30,480,43,440)`, 14 January 2025–8 July 2026 UTC |
| Full | rows `[17,520,43,440)`, 24 July 2023–8 July 2026 UTC |
| Causal warm-up | preceding 336 raw rows for each self-contained segment |
| Uncertainty | 5,000 paired non-circular 168H blocks; seed `20260801` |

## Frozen architecture

The candidate retains the full capped causal BOCPD run-length posterior under a fixed Normal-Inverse-Gamma observation model. It enters long when the posterior mixture probability that the current regime mean exceeds the amortised round-trip fee hurdle is at least 0.80, exits at 0.55 after a minimum 24-hour hold, and otherwise remains in its prior long/cash state. Every decision executes at the next open.

## Performance

| Market | Segment | Candidate net | Candidate Sharpe | Candidate max DD | Trend net | Trend Sharpe | Trend max DD | Candidate turnover |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | train | +67.7278% | +1.3619 | -22.4676% | +126.1452% | +1.5348 | -22.6789% | 164 |
| BTC-USDT | oos | -13.7036% | -0.3000 | -29.5116% | -6.5561% | -0.0730 | -20.3761% | 152 |
| BTC-USDT | full | +44.7430% | +0.6060 | -29.5116% | +111.5303% | +0.9167 | -22.6789% | 316 |
| ETH-USDT | train | +67.3360% | +1.2136 | -19.1585% | +91.4807% | +1.1642 | -29.6290% | 140 |
| ETH-USDT | oos | -34.1476% | -0.5187 | -48.3842% | -12.3843% | -0.0104 | -43.6948% | 182 |
| ETH-USDT | full | +10.1948% | +0.2719 | -48.3842% | +67.9350% | +0.6171 | -47.3033% | 322 |

## OOS benchmark comparison

| Market | Path | Net return | Sharpe | Max DD | Exposure | Turnover | Edge/turnover |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | candidate | -13.7036% | -0.3000 | -29.5116% | +33.6034% | 152 | -0.000902 |
| BTC-USDT | buy-and-hold | -33.0401% | -0.3743 | -53.7385% | +100.0000% | 2 | -0.165201 |
| BTC-USDT | 2,160H trend | -6.5561% | -0.0730 | -20.3761% | +41.6898% | 44 | -0.001490 |
| ETH-USDT | candidate | -34.1476% | -0.5187 | -48.3842% | +35.8951% | 182 | -0.001876 |
| ETH-USDT | buy-and-hold | -43.6022% | -0.2156 | -69.1494% | +100.0000% | 2 | -0.218011 |
| ETH-USDT | 2,160H trend | -12.3843% | -0.0104 | -43.6948% | +39.4444% | 56 | -0.002211 |

## OOS economics and robustness

| Market | Gross | Net | Exposure | Fees | Edge/turnover | Folds positive | Years positive | Delayed net |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | -6.8863% | -13.7036% | +33.6034% | +7.6000% | -0.000902 | 2/6 | 0/2 | -18.9124% |
| ETH-USDT | -27.8774% | -34.1476% | +35.8951% | +9.1000% | -0.001876 | 2/6 | 0/2 | -44.0241% |

## Dependence-aware uncertainty

- **BTC-USDT:** candidate-minus-trend mean hourly net return -0.0616 bps, 95% interval [-0.4204, +0.4023] bps; Sharpe delta -0.2270, 95% interval [-1.5577, +1.5068].
- **ETH-USDT:** candidate-minus-trend mean hourly net return -0.2287 bps, 95% interval [-0.9563, +0.6232] bps; Sharpe delta -0.5082, 95% interval [-2.1598, +1.2920].

## Gate audit

| Gate | BTC-USDT | ETH-USDT |
|---|---:|---:|
| `beats_trend_drawdown` | FAIL | FAIL |
| `beats_trend_return` | FAIL | FAIL |
| `beats_trend_sharpe` | FAIL | FAIL |
| `bootstrap_lb_positive` | FAIL | FAIL |
| `breadth` | FAIL | FAIL |
| `delay_positive` | FAIL | FAIL |
| `edge_per_turnover` | FAIL | FAIL |
| `full_positive` | PASS | PASS |
| `oos_positive` | FAIL | FAIL |
| `turnover_bounded` | PASS | PASS |

## Failure mechanism

The rule was profitable in the training interval and positive over the combined full interval, but reversed in the later development-OOS cohort. OOS gross performance was already negative in both markets, so the rejection is not attributable only to fees. The posterior repeatedly crossed the hysteresis thresholds, producing many short long episodes and substantial fee drag without forecasting persistent next-open edge. It also failed the canonical-trend return, Sharpe, drawdown, temporal-breadth and dependence-aware uncertainty gates in both markets.

A pre-terminal implementation audit repaired the BOCPD changepoint recursion to use the standard shared observation-predictive term for changepoint and growth branches, removed zero-probability log warnings, and corrected a gate-accounting NameError. The invalid dry-run outputs were discarded. No data boundary, prior, hazard, threshold, holding period, fee, benchmark, acceptance gate or valid terminal result was changed.

## Disposition

The architecture is rejected. No canonical strategy mutation, paper authority, live authority, threshold rescue, hazard/prior change, market subset, or OOS-dependent variant is authorised.

**Remaining blocker:** the run-length posterior detects transient positive-mean states but does not distinguish which state transitions will persist long enough to overcome next-open delay and turnover costs.

**Next strategy experiment:** preregister one fixed duration-conditioned transition ensemble that predicts the probability of remaining in a positive regime for a minimum 24-hour horizon, using only the already available causal run-length posterior and no new scalar indicator. It must be trained only on the frozen training segment with a proper scoring rule and evaluated once on a fresh immutable cohort; no threshold or horizon grid is permitted.
