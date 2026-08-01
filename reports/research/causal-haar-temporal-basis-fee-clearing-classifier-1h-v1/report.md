# Direct causal Haar temporal-basis fee-clearing classifier

```text
family          causal-haar-temporal-basis-fee-clearing-classifier-1h-v1
candidate count 2 independent market candidates
parameter grid  0
markets         NEOUSDT, IOTAUSDT independently
bar/provider    immutable public Binance SPOT 1H
fee             exactly 5 bps one way
verdict         reject_causal_haar_temporal_basis_fee_clearing_classifier_1h_v1
```

## Strategy change

The candidate maps each market's latest 512 completed close-to-close returns to 32 fixed coarse Haar coefficients, standardises them on training only, and applies one training-frozen ridge-logistic boundary to a next-24H 10 bp hurdle. Daily 00:00 UTC decisions execute at the same timestamped open and remain long or cash for 24 hours.

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

| Market/segment | Candidate net | Sharpe | Max DD | Turnover | Edge/turn | E2160 net/Sharpe | Always-long net/Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|
| NEOUSDT training | +127.4073% | +1.601233 | -29.1004% | 170 | +0.7495% | +31.7741% / +0.751935 | +25.2478% / +0.712579 |
| NEOUSDT oos | -58.9913% | -0.528537 | -73.0444% | 246 | -0.2398% | +0.9585% / +0.330565 | -66.1694% / -0.266025 |
| NEOUSDT full | -6.7433% | +0.294967 | -73.3141% | 416 | -0.0162% | +33.0371% / +0.523063 | -57.5855% / +0.120172 |
| IOTAUSDT training | +148.6013% | +1.755720 | -28.8248% | 198 | +0.7505% | +6.4331% / +0.485309 | -2.9639% / +0.449685 |
| IOTAUSDT oos | -65.8808% | -0.562686 | -70.2995% | 288 | -0.2288% | +8.6063% / +0.466519 | -46.9281% / +0.180060 |
| IOTAUSDT full | -15.1792% | +0.263644 | -74.6133% | 486 | -0.0312% | +15.5930% / +0.474135 | -48.4496% / +0.277913 |

## OOS robustness

### NEOUSDT

```text
relative positive folds       1/6
candidate/relative years      0/2, 0/2
positive-fold concentration   1.0000
24H delay net / Sharpe         -35.4773% / -0.004774
mean delta CI bp/hour          [-1.9651,+0.5600]
Sharpe delta CI                [-2.4969,+0.7371]
drawdown delta CI              [-0.4739,+0.1553]
gates                           2/11
```

Failed gates: positive_oos_return_and_sharpe, beats_e2160_and_always_long, paired_lower_bounds_positive, edge_per_turnover, turnover, fold_breadth, year_breadth, fold_concentration, delay_stress

### IOTAUSDT

```text
relative positive folds       2/6
candidate/relative years      0/2, 0/2
positive-fold concentration   0.7140
24H delay net / Sharpe         -50.7900% / -0.332557
mean delta CI bp/hour          [-2.7062,+0.7061]
Sharpe delta CI                [-2.8440,+0.8346]
drawdown delta CI              [-0.3794,+0.2151]
gates                           2/11
```

Failed gates: positive_oos_return_and_sharpe, beats_e2160_and_always_long, paired_lower_bounds_positive, edge_per_turnover, turnover, fold_breadth, year_breadth, fold_concentration, delay_stress

## Verdict

`reject_causal_haar_temporal_basis_fee_clearing_classifier_1h_v1`

Markets passing: 0/2.

No canonical mutation, paper/live authority, market subset, or same-cohort change to the basis, window, hurdle, ridge, threshold, cadence, market, benchmark, delay, or sizing is authorised unless every frozen bilateral gate passes.
