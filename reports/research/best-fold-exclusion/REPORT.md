# Best-Fold Exclusion Consistency

## Verdict

**Rejected.** The net rolling out-of-sample return process does not retain a strictly positive 95% lower confidence bound in either development market after removing its single best 90-session fold.

## Hypothesis

BTC-USDT and ETH-USDT each retain a positive annualized arithmetic mean net return after excluding the fold with the highest compounded net return. The joint hypothesis passes only if both fold-block-bootstrap lower confidence bounds are strictly positive.

Economic rationale: a credible adaptive process should not depend on one exceptional OOS fold. This fixed adversarial deletion directly examines the profit-concentration failure reported by the canonical BTC walk-forward result.

## Predeclared specification

- Provider: OKX spot.
- Markets: BTC-USDT and ETH-USDT.
- Timeframe: `1Dutc`.
- Evaluation: 26 non-overlapping 90-session OOS folds, 2,340 observations per market.
- Strategy evidence: persisted net returns with one-bar execution delay and 10-bps turnover cost.
- Stress: remove exactly one fold per market—the fold with the highest compounded net return; earliest fold wins an exact tie.
- Inference: sample the remaining 25 complete 90-session folds with replacement.
- Resamples: 2,000.
- Confidence: 95%.
- Candidate count: one joint hypothesis.

No alternate exclusion count, fold ranking metric, resampling unit, seed, fee, delay, market subset, or threshold was selected after viewing the result.

## Results

| Market | Excluded fold | Excluded fold return | Full annualized mean | Remaining annualized mean | 95% interval | P(mean > 0) |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 4 | 104.439696% | 17.168957% | 5.796263% | [-11.975559%, 23.939737%] | 73.00% |
| ETH-USDT | 4 | 52.125804% | 13.704095% | 7.102486% | [-11.938420%, 25.140764%] | 77.10% |

Both point estimates remain positive, but both lower confidence bounds are negative. One candidate was searched, zero passed, and one was rejected. No improvement claim is made.

## Provenance

- Source workflow: `29922259536`.
- Source artifact: `8530429665` (`quant-research-source-1027-attempt-1`).
- Source archive SHA-256: `da7ab1b69654f50d0da42e2898a69780269e797bcc808dfdaf1f4e04ae9b64df`.
- Source code commit: `a065d4f6c04e21e806e123abdb00a9315055645c`.
- OOS period: 2020-01-11 through 2026-06-07 UTC.
- BTC return-file SHA-256: `539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73`.
- ETH return-file SHA-256: `027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6`.

BTC-USDT and ETH-USDT remain development markets, not untouched holdouts. Resampling reuses observed real returns and does not generate market prices.

## Limitations

The exclusion is chosen adversarially from the complete OOS path and is a stress test, not a live rule. Fold-block resampling preserves each 90-session return path but treats the remaining folds as exchangeable and does not preserve dependence across fold boundaries. Spread, market impact, liquidity, capacity, latency, and partial fills remain unmodeled beyond persisted transaction costs.
