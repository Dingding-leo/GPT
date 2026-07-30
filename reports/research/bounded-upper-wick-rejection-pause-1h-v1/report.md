# Bounded upper-wick rejection pause — terminal evidence

## Frozen architecture

```text
family_id          bounded-upper-wick-rejection-pause-1h-v1
candidate_count    1
parameter_grid     0
bar                1H
execution          next hourly open
fee                exactly 5 bps one way
markets            BTC-USDT and ETH-USDT independently
```

Immediate daily 2,160H trend entry is retained. At most once per positive base-trend regime, the strategy pauses in cash for exactly 168H when trailing 168H range-normalised upper-wick pressure exceeds lower-wick pressure while trailing 168H close return is negative. It automatically resumes after 168H if the base trend remains positive.

## Immutable data and sample

| Item | Frozen value |
|---|---|
| Research parent | `5a0fcc97d1a882f8223656c51f5bb8055f534e38` |
| BTC source | artifact `8704977298`; SHA-256 `92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9` |
| ETH source | artifact `8704978112`; SHA-256 `2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726` |
| Parsed observations | first 43,441 confirmed contiguous 1H bars per market |
| Training | `[2,880,17,520)` |
| Development OOS | `[17,520,43,440)` |
| Full scored | `[2,880,43,440)` |
| Breadth | 12 contiguous 2,160H folds plus calendar years |
| Uncertainty | 5,000 paired non-circular 168H moving-block resamples; seed `20260730` |
| Later suffix | unread and unscored |

## Training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC | Candidate | -42.49% | -0.914 | -52.23% | 32.00 | +1.60% | -147.76 bps |
| BTC | B0 | -41.02% | -0.831 | -55.56% | 138.00 | +6.90% | -32.09 bps |
| BTC | B1 | -41.29% | -0.840 | -55.92% | 28.00 | +1.40% | -159.81 bps |
| ETH | Candidate | -38.09% | -0.564 | -56.06% | 29.00 | +1.45% | -123.55 bps |
| ETH | B0 | -46.84% | -0.744 | -57.75% | 88.00 | +4.40% | -56.53 bps |
| ETH | B1 | -40.59% | -0.584 | -56.95% | 23.00 | +1.15% | -168.77 bps |

## Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC | Candidate | +73.91% | 0.734 | -26.38% | 55.00 | +2.75% | 129.61 bps |
| BTC | B0 | +111.64% | 0.917 | -22.68% | 203.00 | +10.15% | 45.31 bps |
| BTC | B1 | +119.68% | 0.954 | -26.55% | 45.00 | +2.25% | 212.75 bps |
| ETH | Candidate | +74.13% | 0.651 | -44.68% | 38.00 | +1.90% | 218.58 bps |
| ETH | B0 | +68.02% | 0.618 | -47.30% | 139.00 | +6.95% | 58.31 bps |
| ETH | B1 | +74.52% | 0.646 | -47.77% | 30.00 | +1.50% | 283.58 bps |

## Full scored

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC | Candidate | +0.02% | 0.161 | -53.08% | 87.00 | +4.35% | 27.59 bps |
| BTC | B0 | +24.82% | 0.310 | -55.56% | 341.00 | +17.05% | 13.98 bps |
| BTC | B1 | +28.97% | 0.332 | -55.92% | 73.00 | +3.65% | 69.85 bps |
| ETH | Candidate | +7.81% | 0.247 | -56.06% | 67.00 | +3.35% | 70.49 bps |
| ETH | B0 | -10.68% | 0.158 | -57.75% | 227.00 | +11.35% | 13.79 bps |
| ETH | B1 | +3.68% | 0.233 | -56.95% | 53.00 | +2.65% | 87.28 bps |

## Breadth and uncertainty

| Market | Profitable folds | Profitable years | Improved folds/years vs B1 | Residual Sharpe | Mean delta 95% | Sharpe delta 95% |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 5/12 | 3/4 | 4/12; 3/4 | -0.961 | [-25.48%, +3.87%] | [-0.707, +0.132] |
| ETH-USDT | 6/12 | 3/4 | 3/12; 1/4 | -0.062 | [-14.40%, +10.74%] | [-0.296, +0.266] |

## Event diagnostics

### BTC-USDT

- Training pause starts: `4`; OOS pause starts: `8`.
- OOS automatic resumes: `5`; base exits during pause: `3`.
- OOS B1-only exposure: `1152` hours carrying `+23.95%` arithmetic market return.
- OOS incremental fees versus B1: `+0.50%`; exact arithmetic net delta: `-24.45%`.
- Mean market return after pause start: 24H `+0.41%`, 168H `+4.58%`, 720H `+9.42%`.

| Event | Regime | Cash hours vs B1 | Omitted market return | End |
|---:|---:|---:|---:|---|
| 1 | 16 | 120 | -0.34% | base_exit_or_boundary |
| 2 | 23 | 168 | +5.11% | automatic_resume |
| 3 | 30 | 144 | +0.04% | base_exit_or_boundary |
| 4 | 31 | 48 | -1.00% | base_exit_or_boundary |
| 5 | 32 | 168 | +27.18% | automatic_resume |
| 6 | 34 | 168 | -3.02% | automatic_resume |
| 7 | 35 | 168 | +0.78% | automatic_resume |
| 8 | 37 | 168 | -4.80% | automatic_resume |

### ETH-USDT

- Training pause starts: `4`; OOS pause starts: `5`.
- OOS automatic resumes: `4`; base exits during pause: `1`.
- OOS B1-only exposure: `768` hours carrying `+1.62%` arithmetic market return.
- OOS incremental fees versus B1: `+0.40%`; exact arithmetic net delta: `-2.02%`.
- Mean market return after pause start: 24H `-0.59%`, 168H `+0.56%`, 720H `-12.13%`.

| Event | Regime | Cash hours vs B1 | Omitted market return | End |
|---:|---:|---:|---:|---|
| 1 | 17 | 168 | +11.25% | automatic_resume |
| 2 | 21 | 96 | -6.32% | base_exit_or_boundary |
| 3 | 23 | 168 | +2.13% | automatic_resume |
| 4 | 24 | 168 | +1.97% | automatic_resume |
| 5 | 26 | 168 | -7.41% | automatic_resume |

## Diagnostic repair

The first event attribution risked treating every triggered pause as a complete 168H omission even when the base trend ended first. The terminal reproducer instead measures the exact contiguous B1-only interval, distinguishes automatic resumes from base exits during a pause, reconstructs turnover from actual next-open state changes and asserts candidate-minus-B1 arithmetic return from exposure differences and incremental fees to `1e-12`. Two full executions produced byte-identical evidence. No signal, position, fee, metric, bootstrap result, gate or verdict changed.

## Acceptance gates

BTC failed benchmark OOS return, Sharpe, turnover, edge per turnover, fold breadth, residual Sharpe and both uncertainty lower-bound gates. ETH failed benchmark OOS return, turnover, edge per turnover, fold breadth, residual Sharpe and both uncertainty lower-bound gates.

## Verdict

```text
reject_exact_bounded_upper_wick_rejection_pause_family
```

No same-interval wick definition, horizon, pause duration, inequality, cadence, fee or market-specific rescue is authorised. No G1 nomination, paper promotion or live-trading authorisation results.
