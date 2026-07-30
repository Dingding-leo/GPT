# Trend-onset loss-budget exit — terminal report

## Objective and frozen architecture

Enter every new positive daily 2,160H trend immediately. During the same positive-trend regime, track the highest completed daily decision close and exit irreversibly only when peak-to-current log drawdown exceeds one robust trailing 720H volatility scale while total return from onset is non-positive. Candidate count is **1**, with **zero parameter-grid variants**, daily next-open execution and exactly **5 bps one way**.

```text
hourly_return      = log(close_i / close_(i-1))
robust_sigma_720   = 1.4826 × MAD(last 720 completed hourly log returns)
loss_budget        = sqrt(720) × robust_sigma_720
adverse_excursion  = log(highest daily close since onset / current daily close)
failed             = adverse_excursion > loss_budget and log(current/onset) <= 0
```

## Immutable data and sample

| Item | Frozen value |
|---|---|
| Provider | Public confirmed OKX SPOT |
| Markets | BTC-USDT and ETH-USDT independently |
| Source artifacts | BTC `8704977298`; ETH `8704978112` |
| Source rows | 43,941 per market |
| Parsed immutable prefix | 43,441 bars |
| Training | `[2,880,17,520)` |
| Development OOS | `[17,520,43,440)` |
| Full scored | `[2,880,43,440)` |
| OOS breadth | 12 × 2,160H folds plus calendar years |
| Uncertainty | 5,000 paired non-circular 168H blocks; seed 20260730 |
| Later suffix | Unread and unscored |

## Training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn bps | Mean exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | -44.52% | -1.486 | -46.90% | 27.00 | +1.35% | -203.06 | 21.80% |
| BTC-USDT | B0 | -41.02% | -0.831 | -55.56% | 138.00 | +6.90% | -32.09 | 40.18% |
| BTC-USDT | B1 | -41.29% | -0.840 | -55.92% | 28.00 | +1.40% | -159.81 | 40.49% |
| ETH-USDT | CANDIDATE | -22.39% | -0.683 | -31.57% | 22.00 | +1.10% | -100.80 | 11.15% |
| ETH-USDT | B0 | -46.84% | -0.744 | -57.75% | 88.00 | +4.40% | -56.53 | 45.06% |
| ETH-USDT | B1 | -40.59% | -0.584 | -56.95% | 23.00 | +1.15% | -168.77 | 44.60% |

## Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn bps | Mean exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | +147.74% | 1.088 | -22.68% | 45.00 | +2.25% | 238.01 | 54.54% |
| BTC-USDT | B0 | +111.64% | 0.917 | -22.68% | 203.00 | +10.15% | 45.31 | 57.25% |
| BTC-USDT | B1 | +119.68% | 0.954 | -26.55% | 45.00 | +2.25% | 212.75 | 57.32% |
| ETH-USDT | CANDIDATE | +40.29% | 0.492 | -45.47% | 30.00 | +1.50% | 183.96 | 35.65% |
| ETH-USDT | B0 | +68.02% | 0.618 | -47.30% | 139.00 | +6.95% | 58.31 | 49.70% |
| ETH-USDT | B1 | +74.52% | 0.646 | -47.77% | 30.00 | +1.50% | 283.58 | 49.72% |

## Full scored

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn bps | Mean exposure |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | CANDIDATE | +37.45% | 0.380 | -52.68% | 72.00 | +3.60% | 72.61 | 42.72% |
| BTC-USDT | B0 | +24.82% | 0.310 | -55.56% | 341.00 | +17.05% | 13.98 | 51.08% |
| BTC-USDT | B1 | +28.97% | 0.332 | -55.92% | 73.00 | +3.65% | 69.85 | 51.25% |
| ETH-USDT | CANDIDATE | +8.88% | 0.219 | -45.47% | 52.00 | +2.60% | 63.49 | 26.80% |
| ETH-USDT | B0 | -10.68% | 0.158 | -57.75% | 227.00 | +11.35% | 13.79 | 48.03% |
| ETH-USDT | B1 | +3.68% | 0.233 | -56.95% | 53.00 | +2.65% | 87.28 | 47.87% |

## Breadth and uncertainty

| Market | Profitable folds | Profitable years | Concentration | Residual Sharpe | Mean delta 95% | Sharpe delta 95% |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 5/12 | 3/4 | 34.10% | +0.580 | [-8.12%, +16.69%] | [-0.221, +0.530] |
| ETH-USDT | 4/12 | 2/4 | 30.37% | -0.433 | [-42.27%, +18.96%] | [-0.890, +0.533] |

Neither market passed the frozen bilateral scorecard. BTC failed fold breadth and both uncertainty lower-bound gates. ETH failed benchmark return, Sharpe and efficiency, fold/year breadth, residual Sharpe and both uncertainty gates.

## Failure mechanism and diagnostics

### BTC-USDT

- OOS loss-budget exits: **4**.
- B1-only lockout exposure: **720H**, carrying **-11.37%** arithmetic market return.
- Incremental fees candidate minus B1: **+0.00%**.
- Regime outcomes versus B1: **2 improved / 19 tied / 2 worse**; affected exit regimes **2 / 0 / 2**.
- Mean market return after exits: **+0.01% over 24H** and **+2.93% over 168H**.
- Actionable joint-condition frequency: training **2/135**, OOS **4/593**.
- Median OOS loss budget: **+8.19%**; median eligible adverse excursion: **+2.53%**.

### ETH-USDT

- OOS loss-budget exits: **2**.
- B1-only lockout exposure: **3648H**, carrying **+29.89%** arithmetic market return.
- Incremental fees candidate minus B1: **+0.00%**.
- Regime outcomes versus B1: **1 improved / 13 tied / 1 worse**; affected exit regimes **1 / 0 / 1**.
- Mean market return after exits: **-3.84% over 24H** and **-1.20% over 168H**.
- Actionable joint-condition frequency: training **3/71**, OOS **2/387**.
- Median OOS loss budget: **+11.40%**; median eligible adverse excursion: **+5.74%**.

BTC generated a favourable aggregate point estimate: the candidate exceeded B1 on OOS return, Sharpe, drawdown and edge per turnover with unchanged turnover. The four exits removed 720 B1 exposure hours carrying −11.37% arithmetic market return. However, only 5/12 folds were profitable, affected regimes split 2 improved / 2 worse, and both dependence-aware lower bounds crossed zero.

ETH showed the core defect. The two exits were followed by negative mean returns over both 24H and 168H, so they identified immediate weakness, but the irreversible lockout then omitted 3,648 hours carrying +29.89% market return. One affected regime improved and one worsened; the later recovery loss overwhelmed the short-horizon protection.

## Diagnostic repair

The first diagnostic counted the joint loss-budget condition on every positive-trend decision, including mechanically repeated observations after the strategy had already exited and become locked. The terminal diagnostic separates unlocked eligible decisions, first actionable exits, and repeated post-lock conditions. No signal, position, fee, return, benchmark, uncertainty result, acceptance gate or verdict changed.

The complete frozen experiment was rerun twice with byte-identical `result.json` and `protocol.json`.

## Verdict

```text
reject_exact_trend_onset_loss_budget_exit_family
```

No same-interval change to volatility estimator, 720H horizon, multiplier, inequality, regime-return condition, peak definition, re-entry lockout, cadence, fee or market-specific treatment is authorised. There is no G1 nomination, paper promotion or live-trading authorisation.

## Remaining blocker

volatility-scaled adverse excursion identifies short-horizon weakness but an irreversible same-regime lockout still removes profitable ETH recovery; BTC remains promising in aggregate but lacks fold breadth and uncertainty-supported superiority.

## Next strategy experiment

Preregister one own-history-only bounded recovery re-entry architecture: retain immediate onset entry and the same frozen loss-budget exit, but permit at most one same-regime re-entry only after the completed daily close is back above the onset close and the latest 168H return is positive; after re-entry, hold until the base-trend exit. One candidate, no grid and no market-specific rule.
