# Scalar-state family closure meta-analysis

```text
Family          scalar-state-family-closure-meta-analysis-1h-v1
Candidate count 0
Diagnostics     7 source / 1 closure
Parameter grid  0
Markets         BTC and ETH independently
Bar             Immutable public 1H source evidence only
Fee             Exactly 5 bps one way in every source contract
OOS accessed    false
Verdict         reject_scalar_state_gating_architecture_family
```

## Included diagnostic effects

| Source | Group | BTC rho [95% CI] | ETH rho [95% CI] | Both positive |
|---|---|---:|---:|---:|
| #795 lag1_self_contained_b1_payoff_memory | performance_memory | -0.0684 [-0.3630,+0.1693] | -0.0187 [-0.2255,+0.1800] | no |
| #798 trend_boundary_occupancy | b1_geometry | +0.1652 [-0.1720,+0.4488] | +0.1049 [-0.1262,+0.3313] | yes |
| #803 signed_168h_path_coherence | b1_geometry | +0.0077 [-0.4334,+0.4227] | +0.1204 [-0.2171,+0.4738] | yes |
| #806 daily_positive_trend_age | b1_geometry | +0.0589 [-0.0488,+0.1683] | +0.0247 [-0.0847,+0.1189] | yes |
| #814 coinm_basis_compression_resilience | derivatives_exogenous | -0.0497 [-0.1493,+0.0432] | +0.0020 [-0.1031,+0.1051] | no |
| #817 range_acceptance_continuation | spot_auction_geometry | -0.0076 [-0.1194,+0.1091] | -0.0065 [-0.1126,+0.0951] | no |
| #822 lagged_return_range_response_resilience | lagged_vol_response | +0.0137 [-0.0955,+0.1108] | +0.0656 [-0.0402,+0.1740] | yes |

## Family-cluster result

| Independent information group | BTC rho | ETH rho | Bilateral mean | Both positive |
|---|---:|---:|---:|---:|
| b1_geometry | +0.0589 | +0.1049 | +0.0819 | yes |
| derivatives_exogenous | -0.0497 | +0.0020 | -0.0238 | no |
| lagged_vol_response | +0.0137 | +0.0656 | +0.0397 | yes |
| performance_memory | -0.0684 | -0.0187 | -0.0436 | no |
| spot_auction_geometry | -0.0076 | -0.0065 | -0.0070 | no |

```text
BTC grouped median rho        -0.0076
BTC family-bootstrap 95% CI   [-0.0684,+0.0589]
ETH grouped median rho        +0.0020
ETH family-bootstrap 95% CI   [-0.0187,+0.1049]
Bilateral grouped median      -0.0070
Bilateral bootstrap 95% CI    [-0.0436,+0.0819]
Bilateral-positive groups      2/5
Bilateral-positive diagnostics 4/7
Positive source lower bounds   0/14
Exact one-sided sign p         0.8125
Minimum leave-one-group-out    -0.0155
```

Every source interval lower bound is non-positive. Group clustering changes the unclustered positive median into a slightly negative bilateral median because the three related B1 geometry variants no longer receive triple weight.

## Temporal breadth

Descriptive positive gross segments were 16/54 for BTC and 23/54 for ETH. Segment definitions differ across source experiments, so these counts are breadth diagnostics rather than a pooled test.

## Gate verdict

| Gate | Pass |
|---|---:|
| `btc_grouped_median_positive_with_positive_lower_bound` | no |
| `eth_grouped_median_positive_with_positive_lower_bound` | no |
| `bilateral_grouped_median_positive_with_positive_lower_bound` | no |
| `at_least_4_of_5_groups_bilateral_positive` | no |
| `at_least_6_of_7_diagnostics_bilateral_positive` | no |
| `at_least_7_of_14_source_lower_bounds_positive` | no |
| `all_leave_one_group_out_bilateral_medians_positive` | no |
| `one_sided_exact_sign_p_below_0_05` | no |

Only 0/8 frozen gates passed. Verdict: `reject_scalar_state_gating_architecture_family`.

## Strategy-performance fields

No executable candidate was evaluated. Train, OOS and full return/Sharpe, maximum drawdown, benchmark residual, turnover and edge per turnover are therefore not computed. Source target-label turnover is not summed because horizons and label construction differ.

## Limitation

Between-family resampling preserves paired markets but cannot remove dependence from overlapping underlying market samples and targets. The analysis is retrospective closure evidence, not a new independent alpha test.

## Disposition

Further single-scalar gates, indicator renaming, family reweighting and same-sample threshold rescue are closed. The canonical strategy remains unchanged.

**Remaining blocker:** No tested single scalar state has replicated positive fee-aware forward-magnitude information across independent information groups.

**Next experiment:** One fixed Bayesian online change-point long/cash architecture retaining the full causal run-length posterior, with one predeclared turnover-aware decision rule and direct net-performance gates on a fresh immutable cohort.
