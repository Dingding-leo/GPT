# Two-tap daily trend-state ensemble — terminal report

## Frozen strategy change

One own-history-only candidate averaged the current and immediately preceding daily 2,160H endpoint-trend states:

```text
base_t    = 1[close_t > close_(t-2160H)]
target_t  = 0.5 * base_t + 0.5 * base_prev
positions = {0, 0.5, 1.0}
```

The first available daily decision used `base_prev = 0`. Decisions used completed 00:00 UTC bars, executed at the next hourly open, and paid exactly 5 bps per absolute position change. Candidate count was one; parameter-grid count was zero. There was no fitted threshold, feature selector, cross-sectional input, market-specific rule, leverage, shorting, synthetic data, or 15m data.

## Data and sample

| Item | Frozen value |
|---|---|
| Provider | Public confirmed OKX SPOT |
| Markets | BTC-USDT and ETH-USDT independently |
| Artifacts | BTC `8685574446`; ETH `8685572234` |
| Prefix | First 43,441 contiguous confirmed 1H bars |
| Training | `[2,880,17,520)` |
| Development OOS | `[17,520,43,440)` |
| Full scored | `[2,880,43,440)` |
| Breadth | 12 contiguous 2,160H folds plus calendar years |
| Uncertainty | 5,000 paired non-circular 168H blocks, seed `20260731` |
| Later suffix | Unread and unscored |

## Training performance

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC | Candidate | -35.48% | -0.685 | -52.64% | 22.0 | +1.10% | -162.13 bps |
| BTC | B1 | -41.29% | -0.840 | -55.92% | 28.0 | +1.40% | -159.81 bps |
| BTC | B0 | -41.02% | -0.831 | -55.56% | 138.0 | +6.90% | -32.09 bps |
| ETH | Candidate | -44.30% | -0.687 | -58.18% | 17.5 | +0.88% | -259.49 bps |
| ETH | B1 | -40.59% | -0.584 | -56.95% | 23.0 | +1.15% | -168.77 bps |
| ETH | B0 | -46.84% | -0.744 | -57.75% | 88.0 | +4.40% | -56.53 bps |

## Development OOS performance

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC | Candidate | +107.86% | +0.904 | -28.13% | 31.0 | +1.55% | 289.98 bps |
| BTC | B1 | +119.68% | +0.954 | -26.55% | 45.0 | +2.25% | 212.75 bps |
| BTC | B0 | +111.64% | +0.917 | -22.68% | 203.0 | +10.15% | 45.31 bps |
| ETH | Candidate | +69.33% | +0.623 | -45.48% | 21.5 | +1.08% | 381.34 bps |
| ETH | B1 | +74.52% | +0.646 | -47.77% | 30.0 | +1.50% | 283.58 bps |
| ETH | B0 | +68.02% | +0.618 | -47.30% | 139.0 | +6.95% | 58.31 bps |

## Full scored performance

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC | Candidate | +34.12% | +0.358 | -52.64% | 53.0 | +2.65% | 102.31 bps |
| BTC | B1 | +28.97% | +0.332 | -55.92% | 73.0 | +3.65% | 69.85 bps |
| BTC | B0 | +24.82% | +0.310 | -55.56% | 341.0 | +17.05% | 13.98 bps |
| ETH | Candidate | -5.68% | +0.185 | -58.18% | 39.0 | +1.95% | 93.79 bps |
| ETH | B1 | +3.68% | +0.233 | -56.95% | 53.0 | +2.65% | 87.28 bps |
| ETH | B0 | -10.68% | +0.158 | -57.75% | 227.0 | +11.35% | 13.79 bps |

## Breadth and uncertainty

| Market | Profitable folds | Profitable years | Improved folds/years vs B1 | Positive-fold concentration | Residual Sharpe | Mean delta 95% | Sharpe delta 95% |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 5/12 | 3/4 | 4/12; 2/4 | 36.02% | -0.455 | [-6.35%, +3.45%] | [-0.179, +0.102] |
| ETH-USDT | 6/12 | 3/4 | 4/12; 2/4 | 23.08% | -0.213 | [-5.85%, +4.80%] | [-0.132, +0.108] |

Neither market reached 7/12 profitable folds. Both residual Sharpes were negative, and every dependence-aware lower confidence bound was below zero.

## Failure mechanism

### BTC-USDT

```text
OOS compounded delta vs B1       -11.82%
Different exposure hours         1,080 (4.17% of OOS)
One-decision base runs           14 of 45
Turnover saved vs B1             14.0
Onset-reduction contribution     -6.30%
Exit-extension contribution      -0.25%
Fee benefit vs B1                +0.70%
Arithmetic net delta vs B1       -5.85%
Positive / negative events       22 / 23
```

BTC turnover reduction worked exactly as designed: fourteen bounded one-decision base-state runs accounted for all fourteen units of OOS turnover savings. The economic loss came primarily from half-sizing the first day of positive regimes. Onset reductions removed 6.30 arithmetic percentage points, while exit extensions were nearly neutral and fee savings recovered only 0.70 points. The filter therefore suppressed profitable BTC acceleration at trend entry.

### ETH-USDT

```text
OOS compounded delta vs B1       -5.19%
Different exposure hours         721 (2.78% of OOS)
One-decision base runs           8 of 30
Turnover saved vs B1             8.5
Onset-reduction contribution     +2.12%
Exit-extension contribution      -5.63%
Fee benefit vs B1                +0.43%
Arithmetic net delta vs B1       -3.09%
Positive / negative events       15 / 16
```

ETH showed the opposite transition asymmetry. Half-sized onsets added 2.12 arithmetic percentage points by reducing weak first-day exposure, but retaining half exposure after exits cost 5.63 points. Eight isolated one-decision runs plus the OOS boundary explained the 8.5 turnover saving, but fee savings of 0.43 points were too small to offset adverse post-exit carry.

The failure was not a single-event artifact: BTC had 22 positive and 23 negative transition events; ETH had 15 positive and 16 negative events. Equal treatment of onset and exit transitions imposed opposite errors across markets.

## Diagnostic repair and reproducibility

The initial diagnostic reported aggregate timing and fee effects but did not prove why turnover fell despite equal total turnover for ordinary multi-day regimes. The final reproducer partitions daily base-state runs and shows that isolated one-decision runs are cancelled by the two-tap average: BTC saved exactly 14 turnover units from 14 such runs; ETH saved 8 units from 8 runs plus a 0.5 sample-boundary adjustment. No strategy position, return, fee, benchmark, breadth result, bootstrap draw, acceptance gate, or verdict changed.

Two complete final executions were byte-identical.

```text
result-full.json SHA-256
4915c273d34735fb7df2064093e7d36a01b86bbd3f4a7d7e31268e7f2f5644a3
```

## Verdict

```text
reject_exact_two_tap_daily_trend_state_ensemble_family
```

BTC failed OOS return, Sharpe, drawdown, fold breadth, residual Sharpe, and both uncertainty gates. ETH failed OOS return, Sharpe, fold breadth, residual Sharpe, both uncertainty gates, and full-sample positivity. No same-interval change to tap weights, lag count, cadence, trend horizon, boundary convention, fee, benchmark, sample, or market-specific treatment is authorised. There is no G1 nomination, paper promotion, or live-trading authorisation.

**Remaining blocker:** transition smoothing is not directionally transportable. BTC needs immediate onset participation, while ETH benefits from onset smoothing but is harmed by delayed exits. A symmetric linear temporal filter cannot resolve both without a new source of transition information.

**Next strategy experiment:** one materially distinct own-history-only **low-frequency spectral trend-quality state**. Retain the unchanged daily 2,160H binary trend, but at each positive-trend onset compute a fixed 720H ratio of Fourier power below versus above the 24H frequency using only completed hourly log returns. Enter immediately at full exposure and permit one irreversible half downgrade only when low-frequency power is below high-frequency power and the latest 168H return is negative. One candidate, no fitted threshold, no grid, no market-specific rule, and unchanged bilateral gates. This tests frequency-domain path structure rather than another transition average, endpoint algebra, variance ratio, sign entropy, or candle-pressure transform.
