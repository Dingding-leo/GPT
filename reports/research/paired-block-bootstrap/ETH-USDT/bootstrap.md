# Paired moving-block bootstrap: ETH-USDT

## Hypothesis

The walk-forward strategy improves both Calmar and maximum drawdown versus every tested benchmark after preserving serial dependence with paired moving-block resampling.

**Verdict:** `rejected`

## Provenance

- returns CSV SHA-256: `027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6`
- source workflow run: `29841895366`
- source artifact: `8499721759`
- source head SHA: `4c02eccac3d6d81139c73d0b64bb5067756dac93`

## Bootstrap settings

- observations: 2340
- block length: 20
- paired resamples: 2000
- confidence level: 0.950
- seed: 20260722

## Benchmark-relative uncertainty

| Benchmark | Metric | Observed delta | CI lower | CI upper | P(delta > 0) | Supported |
|---|---:|---:|---:|---:|---:|:---:|
| buy_and_hold | calmar | -0.193407 | -2.039648 | 0.479585 | 0.244 | no |
| buy_and_hold | max_drawdown | 0.513907 | 0.144559 | 0.614447 | 0.999 | yes |
| buy_and_hold | cagr | -0.356473 | -1.552973 | 0.248682 | 0.143 | no |
| buy_and_hold | sharpe | -0.346428 | -0.998018 | 0.264203 | 0.123 | no |
| volatility_targeted_long | calmar | -0.212812 | -1.848686 | 0.382189 | 0.177 | no |
| volatility_targeted_long | max_drawdown | 0.380742 | -0.026299 | 0.493317 | 0.968 | no |
| volatility_targeted_long | cagr | -0.290900 | -0.982986 | 0.128386 | 0.084 | no |
| volatility_targeted_long | sharpe | -0.358483 | -1.038635 | 0.291106 | 0.121 | no |
| simple_trend_long_cash | calmar | 0.006912 | -1.337493 | 0.498389 | 0.392 | no |
| simple_trend_long_cash | max_drawdown | 0.434715 | 0.097761 | 0.549814 | 0.996 | yes |
| simple_trend_long_cash | cagr | -0.166855 | -0.902951 | 0.245921 | 0.234 | no |
| simple_trend_long_cash | sharpe | -0.174659 | -0.804485 | 0.360496 | 0.248 | no |

## Interpretation

The joint lower-drawdown and higher-Calmar hypothesis is not supported against every tested benchmark under the declared block-bootstrap specification.

BTC-USDT and ETH-USDT are development markets. This analysis quantifies uncertainty for existing evidence and does not restore untouched-holdout status.
