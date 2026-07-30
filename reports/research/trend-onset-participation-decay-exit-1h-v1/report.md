# Trend-onset participation-decay exit — terminal evidence

## Frozen architecture

```text
family_id          trend-onset-participation-decay-exit-1h-v1
candidate_count    1
parameter_grid     0
bar                1H
execution          next hourly open
fee                exactly 5 bps one way
markets            BTC-USDT and ETH-USDT independently
```

The candidate enters every newly positive daily 2,160H endpoint trend immediately. At completed 00:00 UTC decisions it tracks the maximum 168H positive directional-movement sum observed since onset. It exits once, irreversibly for that base-trend regime, when the current 168H positive-DM sum is strictly below half its maximum and the completed close is below the frozen onset close. A non-positive base trend forces cash and resets the state.

No fitted threshold, parameter grid, alternative ratio, grace period, re-entry, exogenous input, market-specific rule, leverage, cross-sectional operation, pairs/spreads, synthetic data, credentials, accounts, orders or 15m data was used.

## Immutable data and sample

| Item | Frozen value |
|---|---|
| Provider | Public confirmed OKX SPOT |
| BTC source | artifact `8704977298`; SHA-256 `92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9` |
| ETH source | artifact `8704978112`; SHA-256 `2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726` |
| Parsed observations | first 43,441 confirmed contiguous 1H bars per market |
| Source span | 2021-07-24 00:00 UTC to 2026-07-08 00:00 UTC |
| Training | `[2,880,17,520)`; 2021-11-21 to 2023-07-24 |
| Development OOS | `[17,520,43,440)`; 2023-07-24 to 2026-07-08 |
| Full scored | `[2,880,43,440)` |
| Breadth | 12 contiguous 2,160H folds plus calendar years |
| Uncertainty | 5,000 paired non-circular 168H moving-block resamples; seed `20260730` |
| Later suffix | unread and unscored |

## Training

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC | CANDIDATE | -53.66% | -1.732 | -54.82% | 28.00 | +1.40% | -256.29 |
| BTC | B0 | -41.02% | -0.831 | -55.56% | 138.00 | +6.90% | -32.09 |
| BTC | B1 | -41.29% | -0.840 | -55.92% | 28.00 | +1.40% | -159.81 |
| ETH | CANDIDATE | -35.40% | -0.635 | -49.99% | 23.00 | +1.15% | -150.92 |
| ETH | B0 | -46.84% | -0.744 | -57.75% | 88.00 | +4.40% | -56.53 |
| ETH | B1 | -40.59% | -0.584 | -56.95% | 23.00 | +1.15% | -168.77 |

## Development OOS

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC | CANDIDATE | +128.56% | 1.002 | -28.52% | 45.00 | +2.25% | 220.57 |
| BTC | B0 | +111.64% | 0.917 | -22.68% | 203.00 | +10.15% | 45.31 |
| BTC | B1 | +119.68% | 0.954 | -26.55% | 45.00 | +2.25% | 212.75 |
| ETH | CANDIDATE | +74.52% | 0.646 | -47.77% | 30.00 | +1.50% | 283.58 |
| ETH | B0 | +68.02% | 0.618 | -47.30% | 139.00 | +6.95% | 58.31 |
| ETH | B1 | +74.52% | 0.646 | -47.77% | 30.00 | +1.50% | 283.58 |

## Full scored

| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC | CANDIDATE | +5.91% | 0.194 | -59.75% | 73.00 | +3.65% | 37.67 |
| BTC | B0 | +24.82% | 0.310 | -55.56% | 341.00 | +17.05% | 13.98 |
| BTC | B1 | +28.97% | 0.332 | -55.92% | 73.00 | +3.65% | 69.85 |
| ETH | CANDIDATE | +12.74% | 0.267 | -49.99% | 53.00 | +2.65% | 95.03 |
| ETH | B0 | -10.68% | 0.158 | -57.75% | 227.00 | +11.35% | 13.79 |
| ETH | B1 | +3.68% | 0.233 | -56.95% | 53.00 | +2.65% | 87.28 |

## Breadth and uncertainty

| Market | Profitable folds | Profitable years | Improved vs B1 | Residual Sharpe | Annualised mean Δ 95% | Sharpe Δ 95% |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 5/12 | 3/4 | 2/12 folds; 1/4 years | +0.219 | [-8.94%, +11.26%] | [-0.252, +0.352] |
| ETH-USDT | 6/12 | 3/4 | 0/12 folds; 0/4 years | undefined (identical) | [+0.00%, +0.00%] | [+0.000, +0.000] |

## Failure mechanism

### BTC-USDT

- Positive-trend onsets: `22`; actionable participation-decay exits: `2`; locked-cash daily decisions: `14`.
- The participation ratio fell below one half on `100` daily observations, but the complete joint condition triggered on only `2` occasions.
- Mean market return after exits was `-3.16%` over 24H, `+1.07%` over 168H and `-1.82%` over 720H; each estimate is based on only `2` events.
- Omitted B1 exposure: `384` hours carrying `-3.52%` arithmetic market return. Incremental fees versus B1 were `+0.00%` and exact arithmetic net delta was `+3.52%`.
  - regime `17`: `24` hours omitted, market return `-6.48%`.
  - regime `35`: `360` hours omitted, market return `+2.96%`.

### ETH-USDT

- Positive-trend onsets: `15`; actionable participation-decay exits: `0`; locked-cash daily decisions: `0`.
- The participation ratio fell below one half on `74` daily observations, but the complete joint condition triggered on only `0` occasions.
- No development-OOS exit occurred, so the candidate was exactly identical to B1 throughout OOS.
- Omitted B1 exposure: `0` hours carrying `+0.00%` arithmetic market return. Incremental fees versus B1 were `+0.00%` and exact arithmetic net delta was `+0.00%`.

BTC produced a favourable aggregate OOS point estimate because one 24H lockout avoided a sharp loss, but the second lockout omitted profitable recovery and the sole BTC training exit omitted `+27.01%` arithmetic trend return over 2,352 hours. This instability drove BTC full-scored return below B1 and worsened full-sample drawdown. ETH had three training exits but no OOS exits, demonstrating failure of state activation transportability.

## Repaired diagnostic discrepancy

Initial regime-level inspection treated every omitted interval inside a scored span as belonging to a trend that began inside that span. Terminal diagnostics propagate the frozen regime identifier across each sample boundary and separate regimes that began inside the span from a positive trend already active at the boundary; this repairs the training attribution for an overlapping ETH regime. The omitted-exposure mask and arithmetic decomposition are unchanged; no signal, position, fee, metric, bootstrap result, gate or verdict changed.

The final runner also asserts immutable source hashes, contiguous confirmed hourly chronology, allowed binary exposures, exact next-open fee identity, turnover attribution and candidate-minus-B1 arithmetic reconstruction. Two complete executions produced byte-identical `result.json` output.

```text
result.json SHA-256
d01fff2b77b299da4f8abbf7817a65b3f7d0d7627f5544e7c0572c3f7aedfd84
```

## Verdict

```text
reject_exact_trend_onset_participation_decay_exit_family
```

BTC failed drawdown, fold breadth and both dependence-aware uncertainty gates. ETH failed fold breadth, residual-Sharpe and both uncertainty gates because it was exactly B1 OOS. The family is rejected bilaterally. No same-interval modification to the 168H horizon, half-maximum ratio, onset-close condition, lockout, cadence, fee or market-specific treatment is authorised. No G1 nomination, paper promotion or live-trading authorisation results.

**Remaining blocker:** The half-maximum positive-DM decay condition is too sparse and not economically transportable. It fired only twice in BTC development OOS and never in ETH; one BTC exit avoided an immediate loss but the other omitted profitable recovery, while the sole BTC training exit omitted a large positive continuation. The family therefore cannot establish bilateral breadth or uncertainty-supported superiority.

**Next strategy experiment:** One own-history-only bounded upper-wick rejection pause architecture: retain immediate 2,160H trend entry, permit at most one fixed 168H cash pause per positive-trend regime when the latest 168H range-normalized upper-wick sum exceeds the lower-wick sum and the latest 168H close return is negative, then automatically resume if the base trend remains positive. One candidate, no fitted threshold, grid, exogenous input or market-specific rule.
