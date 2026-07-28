# Superseding integration verdict

`reject_for_integration_retain_as_archived_base_specific_development_diagnostic`

The original H1 development comparison remains correctly reconstructed: it improves the rejected fold-local canonical path under the fixed 5 bps one-way model. This does not establish a candidate-neutral turnover rule.

## Strongest-benchmark transfer attack

The unchanged H1 policy hash `437868cc0b2a166cf9b9a3f7dd28848a25664b567a9a6857c333108a3eb7fcf1` was applied to the canonical 2,160-hour `simple_trend_long_cash` target on the same immutable BTC-USDT and ETH-USDT 1H evaluation windows.

For every one of the 25,751 eligible decisions in each market, the prior 168 binary target innovations had median absolute deviation equal to zero. H1 therefore produced a zero no-trade band, suppressed no nonzero revision, and reproduced the benchmark byte-identically.

| Market | Metric | Simple trend | H1 on simple trend | Change |
|---|---:|---:|---:|---:|
| BTC-USDT | Net return | 111.7212% | 111.7212% | 0 |
|  | Sharpe | 0.917431 | 0.917431 | 0 |
|  | Max drawdown | -22.6746% | -22.6746% | 0 |
|  | Annualized turnover | 68.9444 | 68.9444 | 0 |
|  | Edge / turnover | 45.1079 bps | 45.1079 bps | 0 |
| ETH-USDT | Net return | 67.9231% | 67.9231% | 0 |
|  | Sharpe | 0.617047 | 0.617047 | 0 |
|  | Max drawdown | -47.3139% | -47.3139% | 0 |
|  | Annualized turnover | 47.3148 | 47.3148 | 0 |
|  | Edge / turnover | 57.8593 bps | 57.8593 bps | 0 |

Target, position, turnover, fee and return differences are exactly zero. Every paired bootstrap resample therefore also has zero return, Sharpe and turnover difference.

## Consequence

H1 is structurally dependent on a noisy continuous target path. It does not transfer to the strongest canonical fixed benchmark and cannot be described as candidate-neutral. The frozen selector comparison also reports no qualifying nominated policy, so the PR's downstream deployment prerequisite is absent.

Do not merge H1 into the canonical strategy path. Preserve the development evidence only as an archived diagnostic showing that suppressing small revisions can reduce modeled fees for one rejected base path. Any future turnover overlay must be predeclared against the newly authorized strategy architecture and evaluated without retuning on this consumed BTC/ETH window.

Machine-readable evidence: `simple-trend-transfer-stress.json`.
