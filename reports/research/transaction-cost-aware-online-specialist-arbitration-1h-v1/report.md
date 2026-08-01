# Transaction-cost-aware online specialist arbitration

```text
family          transaction-cost-aware-online-specialist-arbitration-1h-v1
candidate count 1
parameter grid  0
markets         RUNEUSDT, KAVAUSDT independently
bar/provider    immutable public Binance SPOT 1H
fee             exactly 5 bps one way
verdict         reject_transaction_cost_aware_online_specialist_arbitration_architecture_v1
```

## Strategy

Three static daily endpoint-trend specialists (720H, 1,440H, 2,160H) are arbitrated using only exponentially discounted strictly prior standalone net log utility. The incumbent changes only after seven daily decisions and only when the challenger's score lead exceeds the frozen 10 bp switching penalty.

## Immutable sample

```text
source months   2023-04 through 2025-12
rows            24,144 per market
training        [2,160,10,800)
OOS             [10,800,23,760)
full scored     [2,160,23,760)
unscored suffix [23,760,24,144)
```

## Performance

| Market/segment | Candidate net | Sharpe | Max DD | Turnover | E720 net/Sharpe | E1440 net/Sharpe | E2160 net/Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|
| RUNEUSDT training | +372.8146% | +2.242184 | -40.0866% | 16.0 | +530.4574% / +2.616318 | +150.1601% / +1.498037 | +179.3841% / +1.572449 |
| RUNEUSDT oos | +15.0558% | +0.455855 | -39.9629% | 22.0 | -62.2575% / -0.726409 | -47.9114% / -0.459690 | -3.8102% / +0.256339 |
| RUNEUSDT full | +444.0008% | +1.317090 | -49.3065% | 38.0 | +137.9504% / +0.846989 | +30.3048% / +0.508433 | +168.7390% / +0.907802 |
| KAVAUSDT training | -15.8290% | -0.014831 | -41.6330% | 32.0 | +21.9079% / +0.642779 | -42.3385% / -0.657191 | -44.1324% / -0.631953 |
| KAVAUSDT oos | -46.6922% | -0.496413 | -75.0566% | 40.0 | -56.6262% / -0.793964 | +16.1231% / +0.459233 | -17.9400% / +0.056029 |
| KAVAUSDT full | -52.1554% | -0.249125 | -75.0566% | 72.0 | -47.1239% / -0.207584 | -33.0416% / -0.005322 | -54.1551% / -0.232338 |

## OOS robustness

### RUNEUSDT

```text
positive folds/years    3/6, 2/2
positive concentration  0.7433
identity switches       8
identity residence      {"E1440": 0.24444444444444444, "E2160": 0.5648148148148148, "E720": 0.19074074074074074}
delayed OOS net         +18.2964%
gates                   10/13
```

| Static expert | Mean-difference 95% CI (bp/hour) | Sharpe-difference 95% CI |
|---|---:|---:|
| E2160 | [-0.3281, +0.6377] | [-0.4794, +0.9641] |
| E1440 | [+0.0483, +1.2212] | [+0.0695, +1.8506] |
| E720 | [+0.1236, +1.6415] | [+0.1877, +2.2824] |

Failed gates: temporal_breadth, fold_concentration, paired_uncertainty

### KAVAUSDT

```text
positive folds/years    1/6, 1/2
positive concentration  1.0000
identity switches       16
identity residence      {"E1440": 0.4981481481481482, "E2160": 0.4111111111111111, "E720": 0.09074074074074075}
delayed OOS net         -43.6436%
gates                   3/13
```

| Static expert | Mean-difference 95% CI (bp/hour) | Sharpe-difference 95% CI |
|---|---:|---:|
| E2160 | [-0.9082, +0.1536] | [-1.4043, +0.2486] |
| E1440 | [-1.1911, -0.1092] | [-1.9316, -0.1774] |
| E720 | [-0.5157, +0.8889] | [-0.8112, +1.5144] |

Failed gates: positive_oos_net, beats_all_static_net, beats_all_static_sharpe, beats_all_static_drawdown, beats_all_static_edge_per_turnover, temporal_breadth, fold_concentration, paired_uncertainty, positive_delayed_oos, positive_full

## Verdict

`reject_transaction_cost_aware_online_specialist_arbitration_architecture_v1`

Markets passing: 0/2.

No canonical mutation, paper authority, live authority, market subset, or same-cohort parameter rescue is permitted unless every frozen bilateral gate passes.
