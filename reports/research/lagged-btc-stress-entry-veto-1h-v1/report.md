# Lagged BTC stress entry-veto 1H experiment

## Frozen strategy change

The single preregistered candidate preserves each instrument's daily 2,160-hour long/cash trend rule and uses one strictly lagged BTC downside-stress state only to delay new entries. The stress feature never forces an exit. Decisions occur at completed 00:00 UTC bars, execute at the next open, and charge exactly 5 bps one-way.

Candidate count: `1`; parameter grid: `0`; preregistration: #622; research parent: `5a0fcc97d1a882f8223656c51f5bb8055f534e38`.

The frozen BTC feature is the minimum over 72 hours of a strictly one-hour-lagged 24-hour BTC log return divided by `sqrt(24)` times lagged 168-hour RMS hourly volatility. Its training-only daily q20 threshold is `-2.2334011815085733`.

## Data and sample

- immutable public OKX SPOT confirmed 1H data;
- BTC-USDT and ETH-USDT evaluated independently;
- 43,941 observations per market;
- training `[2880,17520)`;
- development OOS `[17520,43440)`;
- 12 OOS folds of 2,160 hours;
- later suffix unread and unscored;
- paired non-circular moving-block bootstrap: 5,000 resamples, 168-hour blocks, seed `20260729`.

## Training performance

| Market | Policy | Net return | Sharpe | Max DD | Turnover | Fees | Edge/turnover |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | -41.44% | -0.848 | -56.03% | 26 | 1.30% | -173.26 bps |
| BTC-USDT | Daily trend B1 | -41.29% | -0.840 | -55.92% | 28 | 1.40% | -159.81 bps |
| ETH-USDT | Candidate | -42.44% | -0.634 | -58.29% | 23 | 1.15% | -182.73 bps |
| ETH-USDT | Daily trend B1 | -40.59% | -0.584 | -56.95% | 23 | 1.15% | -168.77 bps |

The entry veto did not improve training economics in either market. Training returns were not used to select or modify the frozen feature or threshold.

## Development-OOS performance

| Market | Policy | Net return | Sharpe | Max DD | Turnover | Fees | Edge/turnover | Entries |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +115.37% | 0.935 | -26.55% | 43 | 2.15% | +217.95 bps | 21 |
| BTC-USDT | Hourly trend B0 | +111.64% | 0.917 | -22.68% | 203 | 10.15% | +45.31 bps | 101 |
| BTC-USDT | Daily trend B1 | +119.68% | 0.954 | -26.55% | 45 | 2.25% | +212.75 bps | 22 |
| ETH-USDT | Candidate | +86.77% | 0.697 | -44.90% | 28 | 1.40% | +327.89 bps | 14 |
| ETH-USDT | Hourly trend B0 | +68.02% | 0.618 | -47.30% | 139 | 6.95% | +58.31 bps | 69 |
| ETH-USDT | Daily trend B1 | +74.52% | 0.646 | -47.77% | 30 | 1.50% | +283.58 bps | 15 |

ETH showed an attractive point estimate: higher return, Sharpe, edge per turnover and lower drawdown than B1. BTC moved in the opposite direction: the veto reduced return and Sharpe and did not improve drawdown.

## Full scored performance

| Market | Policy | Net return | Sharpe | Max DD | Turnover | Fees | Edge/turnover |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +26.12% | 0.317 | -56.03% | 69 | 3.45% | +70.54 bps |
| BTC-USDT | Daily trend B1 | +28.97% | 0.332 | -55.92% | 73 | 3.65% | +69.85 bps |
| ETH-USDT | Candidate | +7.51% | 0.251 | -58.29% | 51 | 2.55% | +97.61 bps |
| ETH-USDT | Daily trend B1 | +3.68% | 0.233 | -56.95% | 53 | 2.65% | +87.28 bps |

## Breadth and uncertainty

| Market | Profitable folds | Profitable years | Positive-fold concentration | Residual Sharpe vs B0/B1 | Mean delta L95 | Sharpe delta L95 |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 5/12 | 3/4 | 34.07% | +0.089 / -0.439 | -0.023288 | -0.066460 |
| ETH-USDT | 6/12 | 3/4 | 20.97% | +0.534 / +1.188 | 0.000000 | 0.000000 |

Neither market met the required 7/12 profitable-fold gate. BTC had negative residual and uncertainty evidence versus B1. ETH's uncertainty lower bounds were exactly zero rather than positive.

## Diagnosed discrepancy

The feature's stress frequency was stable rather than strongly drifting: 20.33% in training and 18.98% in development OOS. The economic relationship, however, reversed across markets.

| Market | B1-only delayed hours | Gross return of delayed exposure | Candidate minus B1 arithmetic net | OOS folds improved | Zero-effect bootstrap mass |
|---|---:|---:|---:|---:|---:|
| BTC-USDT | 72 | +2.12% | -2.02% | 1/12 | 8.20% |
| ETH-USDT | 24 | -6.63% | +6.73% | 1/12 | 31.52% |

BTC omitted predominantly profitable early-trend exposure. ETH's entire apparent improvement came from avoiding one 24-hour losing interval. Because the selector affected only one ETH fold, 31.52% of paired block-bootstrap resamples contained no effect and both lower confidence bounds remained zero. This resolves the discrepancy: the ETH point estimate was episodic, not a broad replicated selector relationship.

## Verdict

`reject_exact_lagged_btc_stress_entry_veto_family`

The candidate fails bilateral qualification. No feature horizon, stress memory, quantile, threshold, entry rule, cadence, timing, fee, market set or bootstrap rescue is authorised on this consumed development interval. There is no G1 nomination, prospective-paper promotion or live-trading authorisation.
