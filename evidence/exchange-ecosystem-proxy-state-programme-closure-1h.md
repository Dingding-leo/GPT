# Public exchange-ecosystem proxy-state programme closure — 1H

Family: `causal-public-exchange-ecosystem-proxy-state-programme-closure-1h-v1`

This closure uses immutable completed evidence only. It adds no market rows, labels, OOS observations, fitting, candidate or parameter grid. Strategy metrics are preserved as `null` because neither bound mechanism authorized an executable mapping.

## Bound evidence

### Group A — lagged OKB exchange-token price impulse

- Owner: issue #1072.
- Exact evidence head: `8ed0096b485f75b5633cd7940776b7f4bcf0cd14`.
- Workflow/artifact: `31234027573` / `9014955096`.
- Candidate/grid: `0/0`; source contract passed; sealed OOS unread.
- HBAR-USDT: 249 opportunities; net rho/slope/tercile `-0.055980 / -0.005153 / -148.84 bp`; adverse `+0.000833 / -0.001144 / -2.02 bp`; fold breadth `1/4 net, 2/4 adverse`; +1H terciles `-190.71 / -44.72 bp`.
- CHZ-USDT: 199 opportunities; net rho/slope/tercile `-0.072686 / -0.006884 / -122.52 bp`; adverse `-0.053382 / -0.004364 / -45.33 bp`; fold breadth `0/4 net, 1/4 adverse`; +1H terciles `-143.14 / -61.96 bp`. CHZ moving-block standardized-slope intervals are entirely negative for net `[-0.013441,-0.001171]` and adverse `[-0.008188,-0.000044]`.
- Original-contract targets passing: `0/2`.
- Terminal verdict: `reject_causal_lagged_okb_risk_appetite_opportunity_information_premise_1h_v1`.

### Group B — lagged BNB exchange-ecosystem activity state

- Owner: issue #1166 / PR #1167.
- Exact evidence head: `a2668a47944f3a7690cdae4610cf7032f26c2876`.
- Workflow/artifact: `31283891670` / `9029302338`.
- Candidate/grid: `0/0`; all three exact 24,144H public native-1H source arms passed; sealed OOS unread.
- BTC-USDT: 285 opportunities; net rho/slope/tercile `+0.015248 / +0.001003 / +21.83 bp`; adverse `-0.057789 / -0.001117 / -17.44 bp`; fold breadth `1/4 net, 2/4 adverse`; positive-net concentration `100%`; E2160 strata and chronological halves fail; +1H terciles `+20.52 / -8.61 bp`.
- ETH-USDT: 241 opportunities; net rho/slope/tercile `-0.014286 / +0.000222 / +22.27 bp`; adverse `-0.134091 / -0.002073 / -35.63 bp`; fold breadth `2/4 net, 1/4 adverse`; positive-net concentration `78.09%`; E2160 strata and chronological halves fail; +1H terciles `+18.20 / -36.32 bp`.
- All required dependence lower bounds fail. The positive outer-tercile terminal-return point estimates are not support because adverse-excursion direction, dependence, breadth/concentration and delay transport fail.
- Original-contract targets passing: `0/2`.
- Terminal verdict: `reject_causal_lagged_bnb_exchange_ecosystem_activity_information_premise_1h_v1`.

## Closure adjudication

All ten frozen closure gates pass:

1. both terminal evidence identities bind;
2. both used real public completed 1H data with causal lagging and exactly 5 bps one way wherever labels were defined;
3. Group A has `0/2` original-contract targets passing;
4. Group B has `0/2` original-contract targets passing;
5. neither group has bilateral dependence-aware support;
6. neither group has bilateral temporal breadth/concentration plus +1H transport;
7. Group B's positive terminal-return tercile point estimates are not counted as support;
8. omitting either group leaves the remaining group unsupported;
9. the conclusion requires no sign reversal, target deletion, favourable-fold deletion, alternate token/venue/window or fitted combination;
10. the conclusion is limited to public exchange-token/exchange-ecosystem proxy states.

Independent support is therefore `0/2`; both leave-one-group-out adjudications retain zero support. Closure-level train/OOS/full return, Sharpe, benchmark comparison, turnover, fee drag, maximum drawdown and edge per turnover remain `null`, not zero.

## Terminal verdict

`reject_reopening_completed_public_exchange_ecosystem_proxy_states_1h_v1`

This closes immediate rescue through another exchange-token price impulse/momentum/volatility/level, exchange-token volume/trade-count/taker-activity proxy, alternate 24H/168H/720H window, z-score/rank/smoothing, sign reversal, threshold, alternate venue/token selected after inspection, target deletion, fitted combination or post-hoc executable mapping.

Canonical mutation: **not authorized**. Paper trading: **not authorized**. Live trading: **not authorized**.
