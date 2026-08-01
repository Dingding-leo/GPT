# causal-temporal-stochastic-dominance-trend-1h-v1

```text
verdict               reject_causal_temporal_stochastic_dominance_trend_1h_v1
candidate_count       2
parameter_grid_count  0
markets_passing       0/2
fee_one_way           0.0005
```

## Market metrics

| Market | Segment | Candidate net | Sharpe | MDD | Turnover | Edge/turnover bp | E2160 net | E2160 Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ICXUSDT | training | -39.382941% | -0.411303 | -65.565966% | 4 | -688.0214 | -20.799500% | 0.050632 |
| ICXUSDT | oos | 15.530563% | 0.467466 | -50.387294% | 4 | 1068.9208 | -10.706726% | 0.187573 |
| ICXUSDT | full | -29.968770% | 0.096101 | -69.599745% | 8 | 190.4497 | -29.279281% | 0.126357 |
| ONTUSDT | training | 63.557250% | 1.006104 | -44.141689% | 2 | 4319.6097 | 21.216659% | 0.657353 |
| ONTUSDT | oos | -28.530345% | -0.043330 | -65.285341% | 6 | -67.8312 | -38.162283% | -0.167487 |
| ONTUSDT | full | 16.893803% | 0.452232 | -65.285341% | 8 | 1029.0290 | -25.042385% | 0.217063 |

## Robustness

### ICXUSDT

- Positive candidate folds: 3/6
- Positive relative folds: 4/6
- Positive-fold concentration: 0.519098
- Mean hourly net delta 95% CI: [-0.147610, 0.597211] bp/h
- Sharpe delta 95% CI: [-0.215224, 0.874038]
- Gates passed: 8/13

### ONTUSDT

- Positive candidate folds: 1/6
- Positive relative folds: 3/6
- Positive-fold concentration: 0.567252
- Mean hourly net delta 95% CI: [-0.470387, 0.645680] bp/h
- Sharpe delta 95% CI: [-0.692008, 0.833760]
- Gates passed: 6/13

## Disposition

**reject_causal_temporal_stochastic_dominance_trend_1h_v1**
