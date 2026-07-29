# Pooled Bayesian Trend-Survival Onset Selector — Terminal Research Report

## Frozen strategy change

The sole candidate replaced heuristic trend-onset confirmation with a common training-only survival-calibration gate. At each instrument’s newly positive daily 2,160H endpoint trend, it computed three causal own-history features: volatility-normalised trend margin, volatility-normalised 168H return, and robust 168H quote-volume slope. Each feature was robustly standardised using that instrument’s training onsets, clipped to `[-3,3]`, and equally weighted. BTC and ETH training onsets were pooled to estimate strict 168H trend survival with a `Beta(1,1)` posterior. Entry was permitted only if the favourable cohort (`score >= 0`) had the preregistered support and a posterior 10th percentile above both 50% and the unconditional survival posterior mean. There was no delayed entry, forced hold, recurrent feature exit, or same-regime re-entry. Execution was next-open and fees were exactly 5 bps one way.

Candidate count: **1**. Parameter-grid variants: **0**.

## Immutable data and sample

| Item | Frozen value |
|---|---|
| Provider | Public confirmed OKX SPOT |
| Markets | BTC-USDT and ETH-USDT independently |
| Bar | 1H |
| Source observations | 43,941 per market |
| Parsed prefix | 43,441 bars |
| Training | `[2,880,17,520)` |
| Development OOS | `[17,520,43,440)` |
| Full scored | `[2,880,43,440)` |
| OOS breadth | 12 contiguous 2,160H folds plus calendar years |
| Later suffix | Unread and unscored |
| Fee | Exactly `0.0005 × absolute position change` |

## Training-only selector calibration

| Quantity | Result |
|---|---:|
| Pooled eligible training onsets | 23 |
| Pooled strict-survival successes | 9 |
| Unconditional posterior mean | 40.00% |
| Favourable cohort support | 11 |
| Favourable successes / failures | 6 / 5 |
| BTC favourable successes / support | 2 / 6 |
| ETH favourable successes / support | 4 / 5 |
| Beta posterior q10 | 36.23% |
| Required lower bound | 50.00% |
| Selector active | **false** |

The support gate passed (`11` total, `6` BTC and `5` ETH), but the conservative calibration gate failed. The favourable cohort survived only `6/11` training onsets, giving a posterior 10th percentile of **36.23%**, below the required **50.00%**. The exact frozen policy therefore remained cash in both markets, as preregistered.

## Training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +0.00% | — | +0.00% | 0 | +0.00% | — |
| BTC-USDT | B1 daily trend | -41.29% | -0.840 | -55.92% | 28 | +1.40% | -159.81 bps |
| BTC-USDT | B0 hourly trend | -41.02% | -0.831 | -55.56% | 138 | +6.90% | -32.09 bps |
| ETH-USDT | Candidate | +0.00% | — | +0.00% | 0 | +0.00% | — |
| ETH-USDT | B1 daily trend | -40.59% | -0.584 | -56.95% | 23 | +1.15% | -168.77 bps |
| ETH-USDT | B0 hourly trend | -46.84% | -0.744 | -57.75% | 88 | +4.40% | -56.53 bps |

## Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +0.00% | — | +0.00% | 0 | +0.00% | — |
| BTC-USDT | B1 daily trend | +119.68% | 0.954 | -26.55% | 45 | +2.25% | +212.75 bps |
| BTC-USDT | B0 hourly trend | +111.64% | 0.917 | -22.68% | 203 | +10.15% | +45.31 bps |
| ETH-USDT | Candidate | +0.00% | — | +0.00% | 0 | +0.00% | — |
| ETH-USDT | B1 daily trend | +74.52% | 0.646 | -47.77% | 30 | +1.50% | +283.58 bps |
| ETH-USDT | B0 hourly trend | +68.02% | 0.618 | -47.30% | 139 | +6.95% | +58.31 bps |

## Full scored sample

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | Candidate | +0.00% | — | +0.00% | 0 | +0.00% | — |
| BTC-USDT | B1 daily trend | +28.97% | 0.332 | -55.92% | 73 | +3.65% | +69.85 bps |
| BTC-USDT | B0 hourly trend | +24.82% | 0.310 | -55.56% | 341 | +17.05% | +13.98 bps |
| ETH-USDT | Candidate | +0.00% | — | +0.00% | 0 | +0.00% | — |
| ETH-USDT | B1 daily trend | +3.68% | 0.233 | -56.95% | 53 | +2.65% | +87.28 bps |
| ETH-USDT | B0 hourly trend | -10.68% | 0.158 | -57.75% | 227 | +11.35% | +13.79 bps |

## Breadth and uncertainty

| Market | Profitable folds | Profitable years | Residual Sharpe vs B1 | Mean Δ lower 95% | Sharpe Δ lower 95% |
|---|---:|---:|---:|---:|---:|
| BTC-USDT | 0/12 | 0/4 | -0.954 | -74.09% | -2.144 |
| ETH-USDT | 0/12 | 0/4 | -0.646 | -84.10% | -1.865 |

Because the common selector was inactive, candidate return, turnover, fees, drawdown and exposure were all zero. Sharpe and edge per turnover were undefined. The exact candidate consequently failed every positive-performance, benchmark-relative, breadth, residual and uncertainty gate, while only the no-worse-drawdown and no-greater-turnover gates passed.

## Failure mechanism and repaired discrepancy

The architecture failed before economic deployment: the pooled training relationship was too weak and heterogeneous for the conservative Bayesian lower bound. BTC favourable onsets survived only `2/6`, whereas ETH favourable onsets survived `4/5`. Pooling improved the point estimate but did not establish a common replicated relationship.

Forward diagnostic evidence did not justify overriding the freeze:

| Market | OOS favourable onsets | Favourable survival | Unfavourable survival | Overall survival |
|---|---:|---:|---:|---:|
| BTC-USDT | 9 | 55.56% | 30.77% | 40.91% |
| ETH-USDT | 5 | 60.00% | 30.00% | 40.00% |

The favourable relationship was directionally positive OOS, but support remained sparse (`9` BTC and `5` ETH events) and the training cross-market calibration was not credible enough to activate. This is evidence against an onset-only binary survival gate, not permission to loosen its posterior threshold.

An initial diagnostic counted training onsets whose 168H label crossed the training boundary. The strategy calibration itself had always excluded those records, so no signal, threshold, position, return, fee, benchmark, acceptance gate or verdict was affected. The terminal reproducer now excludes boundary-crossing labels from both training and OOS diagnostic rates and reports the excluded count explicitly.

## Verdict

```text
reject_exact_pooled_bayesian_trend_survival_onset_family
```

No posterior quantile, prior, support minimum, feature weight, score boundary, target definition, pooling rule, cadence, exit or market-specific rescue is authorised on this consumed development interval. There is no G1 nomination, prospective-paper promotion or live-trading authorisation.

## Remaining blocker

No statistically eligible frozen causal 1H strategy exists. Event-sparse onset calibration lacks enough cross-market support for a conservative binary gate.

## Next strategy experiment

Preregister one own-history-only **multi-horizon fractional trend ensemble** that avoids sparse event labels: at each daily decision, map fixed 720H, 1,440H and 2,160H endpoint-trend signs into a deterministic unlevered `0 / 1/3 / 2/3 / 1` long allocation, execute next-open, and compare directly with B1 under the same bilateral breadth and uncertainty gates. This advances temporal ensemble logic and position sizing without tuning a threshold on the consumed OOS interval.
