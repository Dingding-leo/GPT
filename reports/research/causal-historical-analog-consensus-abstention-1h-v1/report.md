# Causal historical-analog consensus with abstention

```text
family          causal-historical-analog-consensus-abstention-1h-v1
candidate count 2 independent market candidates
parameter grid  0
markets         ALGOUSDT, ATOMUSDT independently
bar/provider    immutable public Binance SPOT 1H
fee             exactly 5 bps one way
verdict         reject_causal_historical_analog_consensus_abstention_1h_v1
```

## Frozen architecture

Each daily query maps the latest 168 completed 1H returns into 28 chronological six-hour sums, RMS-normalises the path, selects 12 nearest fully realised own-history analogs separated by at least 168H, and applies the preregistered median/count hysteresis rule. Exposure is unlevered long or cash; no market pooling, fitting, weighting or parameter search is used.

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

| Market | Segment | Candidate net | Sharpe | Max DD | Turnover | Edge/turn | E2160 net | E2160 Sharpe | Always-long net |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ALGOUSDT | training | -41.4055% | -1.4658 | -54.2436% | 36 | -1.1502% | +53.0677% | +0.9492 | +10.1313% |
| ALGOUSDT | oos | +7.4788% | +0.3168 | -37.5163% | 54 | +0.1385% | +93.1887% | +0.9513 | -12.8516% |
| ALGOUSDT | full | -37.0233% | -0.3309 | -54.2436% | 90 | -0.4114% | +195.7096% | +0.9498 | -3.9263% |
| ATOMUSDT | training | -17.6622% | -0.3845 | -29.8767% | 70 | -0.2523% | -4.5701% | +0.2062 | -25.5062% |
| ATOMUSDT | oos | +61.2151% | +1.3921 | -19.4216% | 58 | +1.0554% | -46.6201% | -0.4519 | -69.3913% |
| ATOMUSDT | full | +32.7409% | +0.5353 | -39.9514% | 128 | +0.2558% | -49.0596% | -0.1884 | -77.1756% |

## OOS robustness

| Market | Positive folds | Positive years | Relative years | Concentration | Complete analogs | Delay net / Sharpe | Mean delta CI bp/h | Sharpe delta CI | Gates |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ALGOUSDT | 4/6 | 1/2 | 1/2 | 72.22% | 100.00% | -11.0628% / -0.0277 | [-2.3858,+0.7035] | [-2.5268,+1.2384] | 6/12 |
| ATOMUSDT | 5/6 | 2/2 | 2/2 | 34.36% | 100.00% | -5.1384% / -0.0276 | [-0.3258,+1.6231] | [-0.0105,+3.6147] | 10/12 |

## Verdict

`reject_causal_historical_analog_consensus_abstention_1h_v1`

Promotion requires every frozen gate to pass independently in both markets. No market-subset promotion or same-cohort rescue is authorised.
