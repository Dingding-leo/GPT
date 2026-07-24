# SOL-USDT sealed architecture holdout

## Hypothesis

The frozen canonical 5 bps full-reselection architecture passes every predeclared retrospective untouched-market gate on SOL-USDT without same-market retuning.

**Verdict:** `rejected`

## Exact 5 bps metrics

| Metric | Strategy | Volatility-targeted long |
|---|---:|---:|
| Net total return | 162.482718% | 125.498459% |
| CAGR | 29.811275% | 24.588960% |
| Sharpe | 1.158959 | 0.671679 |
| Sortino | 2.061616 | 1.020292 |
| Calmar | 1.315328 | 0.380885 |
| Maximum drawdown | -22.664514% | -64.557378% |
| Annualized turnover | 10.904768 | 6.051437 |
| Average absolute exposure | 16.723483% | 65.505607% |

## Fixed selected-path cost stress

| All-in cost | Total return | Sharpe | Maximum drawdown |
|---:|---:|---:|---:|
| 5 bps | 162.482718% | 1.158959 | -22.664514% |
| 7.5 bps | 159.853076% | 1.148189 | -22.826208% |
| 10 bps | 157.249703% | 1.137418 | -23.061136% |
| 15 bps | 152.120722% | 1.115869 | -23.655909% |

## Bootstrap evidence versus volatility-targeted long

| Metric | Point delta | 95% interval | P(delta > 0) | Pass |
|---|---:|---:|---:|:---:|
| Sharpe | +0.487280 | -0.468695 to +1.265901 | 81.05% | no |
| Calmar | +0.934443 | -1.046594 to +2.676554 | 83.35% | no |

The point estimates are materially favorable, but neither predeclared lower confidence bound is positive.

## Stability evidence

- OOS folds: 15.
- Profitable folds: 8/15 (53.33%).
- Best fold: +114.574106%.
- Worst fold: -13.329641%.
- Largest positive-fold contribution: 66.999616%, above the 50% limit.
- Complete calendar years: three (2023-2025), below the required four.
- Complete-year returns: 2023 +135.688848%, 2024 +31.829392%, 2025 -12.507154%.

## Gate status

| Gate | Status |
|---|---|
| frozen_architecture_and_5bps_baseline | **pass** |
| benchmark_relative_risk_adjusted | **fail** |
| fold_stability | **fail** |
| year_stability | **fail** |
| turnover_and_cost_viability | **pass** |
| parameter_neighborhood_stability | **pass** |
| tail_risk | **pass** |
| untouched_market_validation | **fail** |
| separate_spread_slippage_impact_latency | **blocked** |
| capacity | **blocked** |
| prospective_forward_validation | **blocked** |
| overall_live_eligibility | **fail** |

## Candidate accounting

- searched: 1
- passed: 0
- rejected: 1

## Interpretation

The frozen architecture failed one or more predeclared retrospective SOL-USDT holdout gates. The result is rejected and SOL-USDT must not be used for same-market retuning.

The strategy was profitable, cost-viable through 15 bps, parameter-neighborhood stable, and substantially less exposed with shallower tail losses than volatility-targeted long. Those favorable point estimates are insufficient because benchmark-relative confidence, fold concentration, and complete-year evidence failed the fixed gates.

This one-shot result does not permit SOL-USDT retuning. Capacity, separately measured spread/slippage/impact/latency, and prospective forward evidence remain mandatory before paper/live eligibility.
