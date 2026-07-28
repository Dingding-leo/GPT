# Cross-market jump contagion gate v1

## Verdict

`rejected_exact_family_cooldown`

The predeclared one-hour cash gate was tested as a development-only feature diagnostic. It used only the lagged negative-jump state of the other frozen market and did not change the canonical selector, inspect a new market, or consume untouched OOS evidence.

## Frozen rule

For target market `i`, use the other fixed market `j` as a lagged exogenous temporal covariate:

```text
BTC-USDT target <- ETH-USDT lagged jump state
ETH-USDT target <- BTC-USDT lagged jump state
```

At completed hour `t`, define an event when the exogenous return is below the causal empirical 1st percentile of its previous 720 confirmed hourly returns and is negative. If the event occurs, replace the target market canonical exposure with cash for exactly hour `t+1`; otherwise preserve the canonical exposure. Turnover is reconstructed from the candidate position path and charged exactly 5 bps one-way.

## Immutable inputs

- Workflow run: `30347175588`
- Workflow head: `d7cc15839755484b682d6e9094298b8a32f70230`
- OOS interval: `2023-07-24 00:00:00+00:00` through `2026-07-07 23:00:00+00:00`
- OOS hours per market: `25,920`
- Folds per market: `12`
- BTC artifact ZIP SHA-256: `e9bdc2cee531f0b71539a6f4c2b306f2ae702e64bbbe8443ec16bf69c558147a`
- ETH artifact ZIP SHA-256: `1f865024ae9d3ce7aa51bfe72bbab054b0377eef01780c75f60f6e8aa2cdc51e`
- All 13 files in each artifact passed manifest SHA-256 verification.
- Snapshot/OOS return reconstruction error was below `1e-12`.
- Feature missingness in the evaluation rows was zero for both markets.

## Strategy results

| Target | Policy | Net return | Sharpe | Max drawdown | Annual turnover | Edge/turnover | Profitable folds |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | J0 canonical | 43.59% | 0.637 | -26.84% | 45.23 | 33.18 bps | 4/12 |
| BTC-USDT | J1 jump gate | 26.08% | 0.458 | -26.68% | 124.95 | 8.35 bps | 4/12 |
| ETH-USDT | J0 canonical | 16.31% | 0.342 | -29.03% | 62.38 | 12.05 bps | 5/12 |
| ETH-USDT | J1 jump gate | 15.46% | 0.335 | -32.22% | 107.71 | 6.61 bps | 4/12 |

## Feature diagnostic

### BTC-USDT target, ETH-USDT exogenous

- Events: `329` (`1.269%` occupancy)
- Missing feature hours: `0`
- Mean target next-hour return after event: `0.0837%`
- Event-minus-non-event next-hour return: `8.06 bps`
- Candidate benchmark-residual Sharpe: `-1.002`

### ETH-USDT target, BTC-USDT exogenous

- Events: `322` (`1.242%` occupancy)
- Missing feature hours: `0`
- Mean target next-hour return after event: `-0.0239%`
- Event-minus-non-event next-hour return: `-2.63 bps`
- Candidate benchmark-residual Sharpe: `-0.592`

The economic hypothesis failed cross-market consistency. ETH jumps were followed by positive BTC returns on average, so the BTC cash gate systematically removed rebound exposure. BTC jumps were followed by slightly negative ETH returns on average, but the magnitude was far below the turnover and fee burden created by a forced exit and re-entry.

## Tail and turnover effects

- **BTC-USDT:** annualized turnover changed by `+79.72`; worst 24H changed from `-12.87%` to `-13.10%`; worst 168H changed from `-21.09%` to `-21.68%`.
- **ETH-USDT:** annualized turnover changed by `+45.32`; worst 24H changed from `-9.83%` to `-9.31%`; worst 168H changed from `-16.60%` to `-14.83%`.

The gate increased turnover sharply because each sparse event imposed a discrete exit and subsequent re-entry. BTC tail loss was not improved; ETH tail loss improved modestly but net return, edge per turnover, profitable-fold breadth, and benchmark-relative evidence did not qualify.

## Statistical gate

Paired non-circular 168-hour moving-block resampling was performed within each fold, preserving each fold-boundary row exactly once. `5,000` resamples used seed `20260728`. Four one-sided endpoints were Holm-adjusted.

| Target | Endpoint | Observed delta | Basic 95% CI | One-sided 95% lower | Holm p |
|---|---|---:|---:|---:|---:|
| BTC-USDT | Sharpe | -0.179 | [-0.432, +0.077] | -0.400 | 1.000 |
| BTC-USDT | Edge/turnover | -24.83 bps | [-62.60, +13.70] bps | -56.14 bps | 1.000 |
| ETH-USDT | Sharpe | -0.008 | [-0.240, +0.206] | -0.194 | 1.000 |
| ETH-USDT | Edge/turnover | -5.44 bps | [-24.96, +14.48] bps | -21.67 bps | 1.000 |

All confirmatory gates failed. Both markets retained negative residual Sharpe versus the unchanged simple-trend benchmark, and ETH profitable folds fell from 5/12 to 4/12.

## Causal and reconstruction checks

- Future-suffix mutation left all prior causal quantiles and event states unchanged.
- Both market snapshots were complete, unique, strictly increasing, confirmed hourly grids.
- Candidate fees reconstructed exactly as `0.0005 × absolute turnover`.
- Candidate net returns reconstructed from position, asset return and fee within floating-point tolerance.
- Two complete executions produced byte-identical result JSON.

## Cooldown

The exact `720H / 1st-percentile / one-hour cash / BTC↔ETH exogenous mapping` family is rejected. It may not be rescued on the same development window by changing the percentile, lookback, hold time, exposure size, adding volatility filters, or excluding a market.

A genuinely distinct next feature should use actual public trade-flow, funding/basis, open-interest or prospectively collected spread/depth data rather than another candle-derived jump gate.

## Reproduction

```bash
python reports/research/cross-market-jump-contagion-gate-v1/reproduce.py \
  --btc-artifact-dir /path/to/btc_artifact \
  --eth-artifact-dir /path/to/eth_artifact \
  --btc-zip /path/to/btc_artifact.zip \
  --eth-zip /path/to/eth_artifact.zip \
  --output /tmp/cross-market-jump-contagion-gate-v1-result.json
```

Result payload content hash: `5cc1d7860df378c8a78910218c37652cd02c8c227f692bc330fc82138097a2c5`
