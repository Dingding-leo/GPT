# Adaptive market-state DLM programme closure

## Scope

This is a zero-candidate strategy-architecture adjudication for queued issue #538. It uses only terminal immutable evidence from completed strategy families. It acquires no market observation, computes no new target return, opens no OOS sample, fits no model, changes no threshold and creates no executable position path.

```text
family_id                 causal-adaptive-market-state-dlm-programme-closure-1h-v1
queued architecture       adaptive-market-state-dlm-v1 (#538)
candidate / grid          0 / 0
new market rows           0
new target returns        0
new OOS                   0
new fitting/tuning        0
canonical mutation        false
paper/live                false
```

## Falsifiable question

Queued M2 combines four ingredients: target returns/variance/downside/volume/drawdown features; robust aggregate price/variance/downside/volume state; fast/slow recursive linear prediction with 168H predictive-likelihood weighting; and a predictive mean/variance long/cash utility rule with exactly 5 bps one-way turnover cost.

The architecture remains worth a new candidate only if it still contains materially new information and completed evidence supports at least one adaptive or decision mechanism bilaterally after costs. Mere absence of the exact final code path is not sufficient when both its information objects and its adaptation machinery have already been adjudicated.

## Immutable evidence matrix

| Group | Completed programme | Relevant M2 component | Terminal evidence | Independent support |
|---|---|---|---|---|
| A | #841 adaptive temporal overlays | predictive-likelihood/adaptive weighting; turnover-aware arbitration | architecture median net delta `-0.181063 bp/h`, Sharpe delta `-0.241284`; 0/3 positive architecture medians; 0/6 dependence-supported markets; 0/6 breadth-qualified markets | No |
| B | #980 conditional variance/downside states | `rv_ratio`, `downside_ratio`, aggregate volatility/downside state | 0/8 bilateral benchmark groups; 0/8 risk-support groups; 0/8 dependence groups; 0/8 breadth+delay groups | No |
| C1 | #1027 own price-volume directional interactions | `volume_surprise` and price/volume timing | 0/6 supportive groups; executable point gains failed training transport, turnover, breadth or dependence | No |
| C2 | #909 aggregate participation | aggregate activity/volume state | 0/3 bilateral-supportive, broad, OOS-authorised, economic or delay-supported groups | No |
| D | #1050 drawdown/recovery | `drawdown_168h` and recovery-state timing | 0/5 independently admissible mechanisms across 8 fixed targets | No |
| E | #1074 lagged cross-market price risk appetite | aggregate lagged market-return state | 0/3 admissible mechanisms; all leave-one-mechanism subsets rejected | No |
| F | #1060 fixed linear supervised selectors | linear prediction, predictive utility and turnover decision layer | 0/2 supportive units; ETC/FIL fit gains reversed to validation losses; turnover amplified 6.0x/13.5x | No |

All historical executable evidence retained exactly 5 bps one way under its original protocol. Missing metrics in source-only or zero-candidate diagnostics remain null, never zero.

## Four-pillar adjudication

### 1. Target information — closed

The six fixed target features in #538 are not a new information object. `r_1h`/`r_24h` are price return history; `rv_ratio` and `downside_ratio` are inside the completed conditional-variance/downside family; `volume_surprise` is inside completed price-volume families; `drawdown_168h` is inside the completed drawdown/recovery programme. None of the relevant completed families supplied independent bilateral dependence-supported timing.

### 2. Aggregate state — closed

The fixed aggregate state is a robust median of return, volatility/downside and volume-surprise variables. Completed aggregate/cross-market price and participation studies have zero admissible mechanisms. Recombining rejected scalar classes into a median state is not new economic information.

### 3. Adaptive model — closed

The strongest direct evidence is #841: three adaptive temporal architectures produced a negative architecture-level median net effect and negative Sharpe effect versus slow trend, with zero positive architecture medians and zero markets whose paired lower bounds were positive for both return and Sharpe. #1060 independently shows that linear future-utility prediction can reverse sharply from fit to validation.

### 4. Decision / turnover — closed

The proposed conservative utility rule is another predictive-utility selector around fitted return/variance estimates. Completed selector evidence shows profitable benchmark suppression and severe turnover amplification, while adaptive specialist arbitration did not provide robust edge-per-turnover transport. There is no completed bilateral positive incremental evidence supporting this pillar.

## Retention gates

```text
FAIL  materially new information object remains
FAIL  adaptive/decision component has bilateral positive incremental evidence
FAIL  case avoids combining individually rejected mechanisms
PASS  aggregate state itself can remain within causal same-target boundary
FAIL  leave-one-evidence-group-out retains a material independent rationale

passed 1/5
```

Removing any one evidence group leaves the retention verdict unchanged. If A is removed, F still rejects the adaptive/decision machinery. If F is removed, A still rejects adaptive weighting and no completed decision evidence becomes positive. Removing B, C, D or E leaves the target/aggregate information pillars covered by the other rejected information groups. No leave-one-group subset contains completed positive adaptive evidence plus materially new information.

## Strategy accounting

No M0/M1/M2 return path was computed. Therefore training, OOS and full return/Sharpe, benchmark comparison, turnover, fee drag, maximum drawdown, edge per turnover, fold/year breadth, dependence uncertainty and delay metrics for this closure are **null rather than zero**. No OOS observation was consumed.

## Verdict

```text
reject_queued_adaptive_market_state_dlm_v1_as_superseded_recombination
```

Issue #538 should be closed as superseded without implementation. The rejection is limited to its fixed return/variance/downside/volume/drawdown features, robust aggregate price-derived state, fast/slow recursive linear likelihood weighting and predictive-utility long/cash decision layer. It does not reject future architectures built on materially new causal information or a materially new return-generating mechanism.
