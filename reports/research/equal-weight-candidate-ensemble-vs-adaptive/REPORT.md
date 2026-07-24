# Equal-Weight Candidate Ensemble Versus Adaptive Selection

## Hypothesis

An equal-weight ensemble of all 27 declared candidate positions improves both annualized
arithmetic mean net return and annualized Sharpe over the persisted adaptive winner-take-all
path in BTC-USDT and ETH-USDT.

The economic rationale is that model averaging can diversify parameter-selection error and
reduce unnecessary position changes when the highest in-sample score is an unstable estimate.
This is a fixed ensemble over the repository's existing grid, not a new parameter search.

## Fixed design

- Provider: OKX spot.
- Markets: BTC-USDT and ETH-USDT development evidence.
- Timeframe: `1Dutc`.
- Evaluation: 2,385 persisted rolling OOS rows per market, January 11, 2020 through
  July 22, 2026 UTC.
- Constituents: the complete declared `3 × 3 × 3` grid of momentum lookbacks
  `30/90/180`, reversal lookbacks `2/5/10`, and trend weights `0.55/0.70/0.85`.
- Ensemble position: equal-weight mean of all 27 causal, one-bar-delayed candidate positions
  on every session.
- Execution: long/cash, position cap 1, 50% annual volatility target, 30-session volatility
  lookback, 10 bps per unit turnover, cash entry at the OOS start, and continuous positions
  thereafter.
- Comparator: the persisted adaptive winner-take-all rolling OOS path.
- Inference: paired non-circular 20-session moving blocks, 2,000 resamples, 95% confidence.
- Pass rule: both annualized arithmetic mean and annualized Sharpe delta lower bounds must be
  positive in both markets.
- Exactly one joint strategy candidate was tested. No top-k rule, score weighting, alternate
  grid, block length, seed, cost, delay, market subset, or acceptance threshold was searched.

Positive performance delta means the ensemble outperformed the adaptive path. Positive
turnover reduction means the ensemble changed exposure less often.

## Results

| Market | Ensemble mean | Adaptive mean | Mean delta, 95% interval | Ensemble Sharpe | Adaptive Sharpe | Sharpe delta, 95% interval | Turnover reduction, 95% interval |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 17.145991% | 16.842803% | +0.303188% [-10.244974%, +10.529500%] | 0.872193 | 0.718984 | +0.153209 [-0.242195, +0.576647] | +2.507782 [0.369450, 4.959494] |
| ETH-USDT | 17.427430% | 14.018781% | +3.408649% [-7.725421%, +16.044078%] | 0.823913 | 0.554979 | +0.268934 [-0.163805, +0.772337] | +5.112140 [2.868228, 7.145795] |

Point estimates favored the ensemble on mean return, Sharpe, total return, and turnover in both
markets. Turnover reduction had a positive lower bound in both markets. However, every primary
performance interval crossed zero.

## Verdict: rejected

Candidate accounting:

- searched: 1;
- passed: 0;
- rejected: 1;
- fixed ensemble constituents: 27.

The fixed claim that equal-weight model averaging reliably improves both mean net return and
Sharpe is not established. The robust turnover reduction and favorable point estimates make the
ensemble a potentially useful V2 candidate, but they are insufficient to call it an improvement
without positive lower confidence bounds. No alpha, sealed-holdout, or deployment claim is made.

## Provenance

- Source workflow: `30003533823`.
- Source artifact: `8562021482`, `quant-research-source-1927-attempt-1`.
- Source artifact SHA-256:
  `852ef5a2a643d3d8332410ce9f34a9a5b32a8ca69fb42b8058546719c25068e4`.
- Source head: `abb0e4a1837c403026219273a65cc9ec7645d273`.
- BTC return SHA-256:
  `ebf2e4cc63e6b21a2d89420e2c2dd5b3517179baacfd12931f75fb0d99bdd2ce`.
- BTC snapshot SHA-256:
  `407aeba3d1ad4c8e8682a6a689c1c6327139f42bc7587aaae75c77fce047dec1`.
- ETH return SHA-256:
  `bd4fbc471d506069c01b86b39f7726b1bd05752bfd64e75b7d677d2d7f473047`.
- ETH snapshot SHA-256:
  `842b4bbbb0ad7afbe2a1c9ee375443671d818a799266d5dc25cc6a548571ad7f`.

The executable verifies all four source-file digests before parsing or calculation.

## Limitations

BTC-USDT and ETH-USDT remain development markets rather than untouched holdouts. The ensemble
uses equal weights across the declared grid and does not prove that another fixed weighting rule
would work. Moving-block concatenation creates artificial joins and preserves dependence only
within 20-session blocks. The analysis retains the repository's linear 10-bps cost but does not
model nonlinear impact, capacity, changing spreads, latency, or partial fills.
