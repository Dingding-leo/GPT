# SOL-USDT sealed architecture holdout — predeclaration

## Frozen hypothesis

The canonical 5 bps full-reselection architecture frozen on default-branch commit
`9ab1bafddcc67ac78d4c42cd1bfb9e6e96b97449` passes every predeclared retrospective
untouched-market gate on OKX spot `SOL-USDT` without same-market retuning.

Canonical signature:

```text
canonical-5bps-sol-sealed-holdout-v1|market=SOL-USDT|architecture-base=9ab1bafddcc67ac78d4c42cd1bfb9e6e96b97449|source=public-OKX-spot-1Dutc|data-cutoff=2026-07-22T00:00:00Z|baseline=full-reselection-5bps|grid=27-declared-candidates|selection=730|test=90-nonoverlapping|execution=one-bar-delay|costs=5,7.5,10,15bps-fixed-selected-path|benchmark=volatility-targeted-long|benchmark-evidence=paired-noncircular-moving-block-bootstrap-sharpe-and-calmar-lower-bounds-positive|block=20|resamples=2000|confidence=0.95|seed=2026072405|fold-stability=repository-gate|year-stability=at-least-4-complete-years-and-60pct-profitable-and-worst-year-above-minus20pct|turnover=max20-and-15bps-total-return-and-sharpe-positive|neighbourhood=all-perturbations-positive-return-and-sharpe-and-dd-above-minus40pct|tail=maxdd-better-than-benchmark-and-above-minus35pct-and-es-better|candidate-count=1|no-same-market-retuning=true
```

## Why SOL-USDT

Repository code, issue, branch and pull-request searches found no prior `SOL-USDT` research result,
report, canonical signature or implementation. BTC-USDT and ETH-USDT remain development markets.
SOL-USDT is therefore designated once as the previously unused architecture holdout required by
Phase 3. This designation is made before the SOL history is downloaded or inspected.

## Frozen architecture

- public OKX spot `1Dutc` completed candles only;
- fixed cutoff: `2026-07-22T00:00:00Z`;
- long/cash position bounds `[0, 1]`;
- one-bar execution delay;
- one-way 5 bps exchange-fee baseline;
- fixed selected-path repricing at 7.5, 10 and 15 bps;
- 30/90/180 momentum, 2/5/10 reversal and 0.55/0.70/0.85 trend-weight grid;
- 730-bar selection windows and non-overlapping 90-bar OOS folds;
- 27 candidates per fold;
- no SOL-USDT parameter, formula, threshold, market-window or gate changes after result exposure.

## Predeclared retrospective gates

The single candidate passes the untouched-market gate only when all of the following pass:

1. **Benchmark-relative risk-adjusted evidence:** paired non-circular 20-session moving-block
   bootstrap lower bounds for strategy-minus-volatility-targeted-long Sharpe and Calmar are both
   strictly positive over 2,000 resamples at 95% confidence.
2. **Fold stability:** the repository fold-stability gate passes.
3. **Year stability:** at least four complete calendar years, at least 60% profitable complete
   years, and the worst complete year is greater than -20%.
4. **Turnover and cost viability:** annualized absolute turnover is at most 20 and the frozen path
   retains positive total return and Sharpe at 15 bps all-in cost.
5. **Parameter-neighbourhood stability:** every declared perturbation has positive total return,
   positive Sharpe and maximum drawdown above -40%.
6. **Tail risk:** maximum drawdown is shallower than volatility-targeted long, is no worse than
   -35%, and 5% expected shortfall is less severe than volatility-targeted long.
7. **Integrity:** the report remains bound to the frozen 5 bps configuration, SOL-USDT provenance,
   the 27-candidate grid and the fixed data cutoff.

Candidate accounting is fixed at one. No alternative market, threshold, bootstrap setting,
benchmark, candidate family or pass rule will be selected after viewing the result.

## Live eligibility

Even a supported retrospective SOL result cannot by itself make the candidate live eligible.
Separately measured spread, slippage, market impact and latency, capacity, and prospective forward
validation remain mandatory blocked gates. A rejected SOL result is retained as rejection and must
not trigger SOL-specific retuning.
