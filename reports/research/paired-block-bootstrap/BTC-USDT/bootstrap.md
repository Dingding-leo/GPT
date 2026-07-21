# Paired moving-block bootstrap: BTC-USDT

## Hypothesis

The walk-forward strategy improves both Calmar and maximum drawdown versus every tested benchmark after preserving serial dependence with paired moving-block resampling.

**Verdict:** `partially supported`

## Provenance

- returns CSV SHA-256: `539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73`
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
| buy_and_hold | calmar | 0.041527 | -1.290839 | 0.853679 | 0.412 | no |
| buy_and_hold | max_drawdown | 0.475274 | 0.110704 | 0.561398 | 0.998 | yes |
| buy_and_hold | cagr | -0.220790 | -0.923726 | 0.213551 | 0.181 | no |
| buy_and_hold | sharpe | -0.107924 | -0.780195 | 0.562188 | 0.352 | no |
| volatility_targeted_long | calmar | 0.158143 | -0.943831 | 0.905404 | 0.538 | no |
| volatility_targeted_long | max_drawdown | 0.429577 | 0.079806 | 0.516768 | 0.996 | yes |
| volatility_targeted_long | cagr | -0.114371 | -0.612773 | 0.221873 | 0.266 | no |
| volatility_targeted_long | sharpe | -0.007029 | -0.654356 | 0.646435 | 0.468 | no |
| simple_trend_long_cash | calmar | 0.082750 | -0.985515 | 0.739384 | 0.526 | no |
| simple_trend_long_cash | max_drawdown | 0.283855 | 0.036124 | 0.450023 | 0.988 | yes |
| simple_trend_long_cash | cagr | -0.103302 | -0.564648 | 0.186911 | 0.253 | no |
| simple_trend_long_cash | sharpe | -0.014719 | -0.592688 | 0.520771 | 0.457 | no |

## Interpretation

The lower-drawdown result survives the paired block bootstrap against all tested benchmarks, but the Calmar advantage does not. The existing risk-control label is therefore only partially supported and must not be strengthened to a statistically confirmed Calmar advantage.

BTC-USDT and ETH-USDT are development markets. This analysis quantifies uncertainty for existing evidence and does not restore untouched-holdout status.
