# Calendar-Year OOS Drawdown Stability

## Hypothesis

The walk-forward strategy reduces maximum drawdown versus the volatility-targeted-long benchmark in at least 6 of 7 eligible calendar-year OOS blocks for each BTC-USDT and ETH-USDT, with median annual drawdown reduction of at least 0.10.

Canonical signature: `calendar-year-dd-stability-v1|markets=BTC-USDT,ETH-USDT|benchmark=vol-targeted-long|min_obs=150|required_years=6|required_median_reduction=0.10|candidate_count=0`

## Evidence boundary

- Source workflow run: `29841895366`
- Source artifact: `8499721759`
- Source artifact SHA-256: `dbe25282321fa1d1fdafa2945c1a45e6a6481060d693956fd5fb3225b03f3fd7`
- Source head: `4c02eccac3d6d81139c73d0b64bb5067756dac93`
- Candidate count: `0` (no parameter or hypothesis search in this run)
- Benchmark: volatility-targeted long, evaluated from the same OOS return artifact
- Eligible year rule: at least `150` daily OOS observations
- Predeclared support rule: at least `6` successful years and median annual drawdown reduction of at least `0.10` for each instrument

## Result

**Joint verdict: supported as a persistent risk-control effect; no return or alpha advantage claimed.**

### BTC-USDT

- Source returns SHA-256: `539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73`
- OOS range: `2020-01-11T00:00:00+00:00` to `2026-06-07T00:00:00+00:00`
- Eligible calendar years: `7`
- Years with lower drawdown: `7/7`
- Median annual drawdown reduction: `0.227979`
- Years with higher total return: `4/7`

| Year | Obs | Strategy return | Vol-target return | Strategy MDD | Vol-target MDD | DD reduction |
|---:|---:|---:|---:|---:|---:|---:|
| 2020 | 356 | 0.473094 | 1.370719 | -0.286071 | -0.482297 | 0.196226 |
| 2021 | 365 | 0.371811 | 0.355307 | -0.147406 | -0.375384 | 0.227979 |
| 2022 | 365 | -0.218828 | -0.601701 | -0.220533 | -0.619565 | 0.399032 |
| 2023 | 365 | 0.267445 | 1.393305 | -0.148905 | -0.199940 | 0.051034 |
| 2024 | 366 | 0.461229 | 1.229924 | -0.182188 | -0.242917 | 0.060729 |
| 2025 | 365 | -0.043644 | -0.066121 | -0.089860 | -0.320293 | 0.230433 |
| 2026 | 158 | -0.100815 | -0.277817 | -0.107666 | -0.372362 | 0.264696 |

### ETH-USDT

- Source returns SHA-256: `027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6`
- OOS range: `2020-01-11T00:00:00+00:00` to `2026-06-07T00:00:00+00:00`
- Eligible calendar years: `7`
- Years with lower drawdown: `7/7`
- Median annual drawdown reduction: `0.172458`
- Years with higher total return: `3/7`

| Year | Obs | Strategy return | Vol-target return | Strategy MDD | Vol-target MDD | DD reduction |
|---:|---:|---:|---:|---:|---:|---:|
| 2020 | 356 | 0.143000 | 2.961610 | -0.223397 | -0.356914 | 0.133517 |
| 2021 | 365 | 0.650999 | 1.879064 | -0.176095 | -0.271562 | 0.095468 |
| 2022 | 365 | -0.094957 | -0.553301 | -0.156433 | -0.598846 | 0.442412 |
| 2023 | 365 | 0.180279 | 0.823615 | -0.094991 | -0.267449 | 0.172458 |
| 2024 | 366 | -0.181757 | 0.585090 | -0.279174 | -0.367766 | 0.088592 |
| 2025 | 365 | 0.388216 | -0.037978 | -0.114891 | -0.464029 | 0.349137 |
| 2026 | 158 | -0.145743 | -0.386319 | -0.157347 | -0.494452 | 0.337105 |

## Calculation

For each eligible calendar-year block and each return series:

1. compound daily returns to obtain annual total return;
2. construct the within-year NAV from `1.0`;
3. calculate maximum drawdown as the minimum of `NAV / running_max(NAV) - 1`;
4. define drawdown reduction as `abs(benchmark MDD) - abs(strategy MDD)`;
5. count a year as successful only when the reduction is strictly positive.

The source CSV timestamps were parsed as UTC and checked for strict increasing order and uniqueness before calculation. Source file bytes were independently rehashed before analysis and matched the declared SHA-256 values.

## Interpretation

The lower-drawdown effect is persistent across calendar-year OOS blocks for both development markets. Return outperformance is not persistent, so this result supports a risk-control interpretation rather than an alpha or risk-adjusted-return claim.

## Limitations

- BTC-USDT and ETH-USDT are development markets, not untouched holdouts.
- Calendar-year blocks are not assumed independent; no binomial p-value is claimed.
- The test concerns drawdown persistence only, not Sharpe, Calmar, CAGR, or alpha.
- The 2026 block is partial but eligible under the predeclared 150-observation minimum.
- This analysis uses one predeclared benchmark and one predeclared threshold pair; no alternate thresholds were searched.
