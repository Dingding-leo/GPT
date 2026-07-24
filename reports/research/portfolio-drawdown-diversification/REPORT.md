# Paired Portfolio Drawdown Diversification

## Hypothesis

A fixed-initial-weight 50/50 BTC-USDT/ETH-USDT portfolio with no rebalancing has less severe maximum drawdown than each sleeve. The hypothesis passes only if both 95% paired moving-block-bootstrap lower bounds for `portfolio max drawdown - sleeve max drawdown` are positive.

Canonical signature:

`paired-portfolio-drawdown-diversification-v1|markets=BTC-USDT,ETH-USDT|portfolio=fixed-initial-weights-50-50-no-rebalancing|metric=max-drawdown-reduction-vs-each-sleeve|resampling=paired-noncircular-moving-block|block=20|resamples=2000|confidence=0.95|seed=20260722|candidate_count=1`

## Economic rationale

Cross-sleeve diversification should reduce drawdown when BTC and ETH strategy losses are not perfectly synchronized. Fixed 50/50 initial weights and no rebalancing match the repository's merged portfolio construction and avoid same-sample weight optimization.

## Fixed specification

- OKX spot BTC-USDT and ETH-USDT, `1Dutc`;
- persisted net rolling OOS strategy returns;
- fixed 50/50 initial capital, no rebalancing;
- paired non-circular 20-day moving blocks;
- 2,000 resamples, 95% confidence, seed 20260722;
- one candidate specification.

## Verdict: rejected

| Sleeve comparison | Sleeve max drawdown | Portfolio max drawdown | Point reduction | 95% interval | P(reduction > 0) |
|---|---:|---:|---:|---:|---:|
| BTC-USDT | -29.0984% | -26.2087% | 2.8897% | -9.8050% to 16.3258% | 64.30% |
| ETH-USDT | -27.9174% | -26.2087% | 1.7088% | -4.6865% to 23.3079% | 87.15% |

The observed portfolio drawdown was shallower than both sleeve drawdowns, but both lower confidence bounds were negative. The development evidence does not establish reliable maximum-drawdown diversification at the repository's confidence standard.

## Provenance

- workflow `29883451981`;
- artifact `8515639605` (`quant-research-426`);
- archive SHA-256 `396903281f1ef4ec71edbe0dded7c091c4c3545ffbaa7a502cc15bda4880b478`;
- 2,340 aligned OOS daily observations, 2020-01-11 through 2026-06-07 UTC;
- BTC return SHA-256 `539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73`;
- ETH return SHA-256 `027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6`.

## Claim boundary

This is development-market evidence, not a fresh holdout or evidence of alpha. It does not model liquidity, capacity, spread, impact, latency, partial fills, or live execution.
