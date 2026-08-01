# Causal lagged-BTC entry-gating family closure

## Terminal result

```text
family_id              causal-lagged-btc-entry-gating-family-closure-1h-v1
classification         preregistered completed-evidence family closure
architecture_groups    3
new_candidates         0
parameter_grid         0
new market data        0
new OOS                 0
bar                     1H
fee                     exactly 5 bps one way in source candidates
supportive groups       0/3
verdict                 reject_causal_lagged_btc_entry_gating_family
```

The closure treats each completed architecture as one independent evidence unit. It does not recompute a source strategy, inspect a new candle, consume another OOS observation, change a sign or threshold, filter a market, or combine the three states.

## Architecture support audit

| Architecture group | Source valid / valid fail-closed | Bilateral positive OOS | Bilateral B1 superiority | Positive lower bounds | Fold/year breadth | State transport/support | Supportive |
|---|---:|---:|---:|---:|---:|---:|---:|
| Downside-stress entry veto | Pass | Pass | Fail | Fail | Fail | Fail | No |
| Liquidity-stress recovery entry | Pass | Fail | Fail | Fail | Fail | Fail | No |
| Downside-shock absorption entry | Pass | Fail | Fail | Fail | Fail | Fail | No |

```text
source-valid groups                         3/3
bilateral positive-OOS groups               1/3
bilateral B1-superior groups                0/3
positive dependence-bound groups            0/3
temporal-breadth groups                     0/3
state-transport/event-support groups        0/3
supportive groups                           0/3
leave-one-group-out supportive count        0 after every omission
```

All family gates except source validity fail. The frozen rule required at least two materially distinct supportive groups and survival after every leave-one-group-out omission.

## Data and sample

All source experiments used immutable public confirmed OKX SPOT 1H BTC-USDT and ETH-USDT data independently:

```text
observations per market    43,941
warm-up                    [0,2,880)
training                   [2,880,17,520)
development OOS            [17,520,43,440)
full scored                [2,880,43,440)
OOS folds                  12 × 2,160H
represented OOS years      4
later suffix               unread
execution                  completed daily bar -> next open
fee                        0.0005 × absolute exposure change
```

BTC CSV SHA-256: `92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9`.  
ETH CSV SHA-256: `2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726`.

## Complete source performance

| Group | Market | Segment | Candidate net | Sharpe | Max DD | Turnover | Edge/turn bp | B1 net | B1 Sharpe |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| A — downside-stress veto | BTC-USDT | training | -41.44% | -0.848 | -56.03% | 26 | -173.258 | -41.29% | -0.840 |
| A — downside-stress veto | BTC-USDT | oos | +115.37% | +0.935 | -26.55% | 43 | +217.950 | +119.68% | +0.954 |
| A — downside-stress veto | BTC-USDT | full | +26.12% | +0.317 | -56.03% | 69 | +70.538 | +28.97% | +0.332 |
| A — downside-stress veto | ETH-USDT | training | -42.44% | -0.634 | -58.29% | 23 | -182.731 | -40.59% | -0.584 |
| A — downside-stress veto | ETH-USDT | oos | +86.77% | +0.697 | -44.90% | 28 | +327.890 | +74.52% | +0.646 |
| A — downside-stress veto | ETH-USDT | full | +7.51% | +0.251 | -58.29% | 51 | +97.610 | +3.68% | +0.233 |
| B — liquidity-stress recovery | BTC-USDT | training | +19.69% | +0.561 | -21.73% | 4 | +575.953 | -41.29% | -0.840 |
| B — liquidity-stress recovery | BTC-USDT | oos | +0.00% | — | +0.00% | 0 | — | +119.68% | +0.954 |
| B — liquidity-stress recovery | BTC-USDT | full | +19.69% | +0.337 | -21.73% | 4 | +575.953 | +28.97% | +0.332 |
| B — liquidity-stress recovery | ETH-USDT | training | -15.82% | -0.169 | -32.41% | 10 | -89.070 | -40.59% | -0.584 |
| B — liquidity-stress recovery | ETH-USDT | oos | +0.00% | — | +0.00% | 0 | — | +74.52% | +0.646 |
| B — liquidity-stress recovery | ETH-USDT | full | -15.82% | -0.102 | -32.41% | 10 | -89.070 | +3.68% | +0.233 |
| C — shock absorption | BTC-USDT | training | +0.00% | — | +0.00% | 0 | — | -41.29% | -0.840 |
| C — shock absorption | BTC-USDT | oos | +0.00% | — | +0.00% | 0 | — | +119.68% | +0.954 |
| C — shock absorption | BTC-USDT | full | +0.00% | — | +0.00% | 0 | — | +28.97% | +0.332 |
| C — shock absorption | ETH-USDT | training | +0.00% | — | +0.00% | 0 | — | -40.59% | -0.584 |
| C — shock absorption | ETH-USDT | oos | +0.00% | — | +0.00% | 0 | — | +74.52% | +0.646 |
| C — shock absorption | ETH-USDT | full | +0.00% | — | +0.00% | 0 | — | +3.68% | +0.233 |

Undefined Sharpe and edge per turnover remain undefined and fail the family gates; they are not coerced to zero.

## Group A — lagged BTC downside-stress veto

This was the only architecture with positive OOS net return in both targets. It still failed as family support:

- BTC returned **+115.37%** versus B1 **+119.68%**, with Sharpe `0.935` versus `0.954`; its benchmark-relative lower bounds were `-0.023288` for annualised mean delta and `-0.066460` for Sharpe delta.
- ETH returned **+86.77%** versus B1 **+74.52%**, but both lower bounds were exactly zero. `31.52%` of bootstrap draws had no selector effect.
- Breadth was only `5/12` BTC and `6/12` ETH profitable folds. Each market's entire benchmark difference occurred in one fold.
- BTC vetoed 72 profitable hours with +2.12% gross return. ETH avoided 24 losing hours with -6.63% gross return. Stable activation frequency therefore did not imply a transportable economic sign.

## Group B — lagged BTC liquidity-stress recovery

The common state occurred on `16.56%` of training decisions and `0.00%` OOS. Median BTC quote volume rose `2.385×`, while the return-per-volume weekly stress scale fell to `0.368×` training. The candidate remained cash OOS in both targets, producing zero turnover and undefined Sharpe while B1 returned +119.68% in BTC and +74.52% in ETH.

The architecture encoded secular quote-volume scale rather than a stable liquidity state. OOS lower bounds were sharply negative: BTC `-0.740933 / -2.144148` and ETH `-0.840973 / -1.865265` for annualised mean and Sharpe deltas.

## Group C — lagged BTC downside-shock absorption

The performance-free training support gate failed before target returns could enable the selector:

```text
eligible training decisions       610
state decisions                     6
minimum required                   20
unique supporting shocks            1
largest-event concentration       100%
selector enabled                  false
```

The candidate correctly failed closed to cash. OOS state incidence later rose to 61 decisions supported by 13 shocks, but that post-declaration observation cannot override a failed training-only support gate.

## Failure mechanism and disposition

The family fails through complementary mechanisms:

1. a stable-frequency veto had a market-dependent sign and one-fold concentration;
2. an absolute return-per-volume state collapsed under secular volume scaling;
3. an event state lacked independent training support.

No architecture delivered bilateral B1 superiority, strictly positive dependence-aware lower bounds, preregistered fold/year breadth, or broad exogenous-state transport. The consumed BTC/ETH cohort is closed to alternate BTC stress memories, quantiles, return/volume normalisations, shock thresholds, wick/recovery windows, support cutoffs, market subsets, sign reversal, state voting or post-hoc combinations.

```text
architecture accepted       no
candidate promoted          no
canonical strategy changed  no
paper/live authority        none
```

## Remaining alpha blocker

The programme still lacks a low-turnover exogenous state that separates fragile from profitable E2160 entries across independent markets. BTC price and volume stress is too endogenous to the target opportunity, too regime-scale-sensitive, or too event-sparse.

## Next sole architecture

`causal-stablecoin-quote-stress-entry-veto-1h-v1` will test a materially orthogonal mechanism on fresh SOLUSDT and XRPUSDT cohorts: a strictly lagged robust `USDCUSDT` premium as a measure of USDT quote-currency dislocation. The candidate will preserve each target's own 2,160H trend and veto only new entries during persistent positive stablecoin-premium stress. It introduces no BTC input, ranking, relative-value position, shorting, leverage, parameter grid, credentials or private data.
