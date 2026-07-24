# Lagged-volatility regime consistency

## Hypothesis

For both BTC-USDT and ETH-USDT, the strategy's net out-of-sample returns have a positive
annualized arithmetic mean in both low- and high-volatility regimes. The hypothesis passes only
if all four 95% paired moving-block-bootstrap lower bounds are above zero.

The regime variable is the standard deviation of the previous 20 asset returns:

```text
asset_return.shift(1).rolling(20).std(ddof=1)
```

The shift is essential: the current session's return cannot determine its own regime. Low and high
volatility are split at the median prior volatility, recomputed inside every bootstrap sample.
Arithmetic means are used because regime observations are non-contiguous; the report does not
present a regime-subset CAGR.

Canonical signature:

```text
lagged-volatility-regime-consistency-v1|markets=BTC-USDT,ETH-USDT|regime=median-of-prior-20d-realized-vol-recomputed-per-resample|prior-volatility=asset-return-shift1-rolling-std-ddof1|metric=annualized-arithmetic-mean-net-return|lookback=20|annualization=365|block=20|resamples=2000|confidence=0.95|seeds=BTC-USDT:20260722,ETH-USDT:20260723|candidate_count=1
```

## Economic rationale

A robust long/cash risk-control strategy should not require only one volatility environment to
produce positive net returns. Conditioning on strictly lagged volatility tests whether the observed
OOS return is broad across calm and stressed regimes rather than being confined to one state.

## Candidate accounting

Exactly one specification was tested:

- prior-volatility lookback: 20 daily observations;
- regime threshold: median, recomputed per resample;
- metric: annualized arithmetic mean net strategy return in each regime;
- paired moving blocks: 20 observations, without circular wrapping;
- resamples: 2,000;
- confidence: 95%;
- deterministic seeds: 20260722 for BTC and 20260723 for ETH.

No alternative lookback, threshold, regime count, volatility estimator, return metric, block length,
seed, market subgroup, strategy parameter, transaction cost, execution delay, or split was searched
after observing the result.

## Results

| Market | Regime | Point annualized mean | 95% interval | P(mean > 0) | Pass |
|---|---|---:|---:|---:|---|
| BTC-USDT | Low volatility | 4.5875% | [-18.6479%, 35.2808%] | 67.30% | No |
| BTC-USDT | High volatility | 30.3918% | [2.2181%, 63.5277%] | 98.10% | Yes |
| ETH-USDT | Low volatility | 2.7388% | [-26.9053%, 31.5943%] | 59.25% | No |
| ETH-USDT | High volatility | 24.9056% | [-3.0591%, 52.7711%] | 95.65% | No |

Each market contributed 2,320 eligible observations after the 20-observation lagged-volatility
warmup, split into 1,160 low- and 1,160 high-volatility observations at the point estimate.

## Verdict: rejected

The BTC high-volatility regime passed, but the BTC low-volatility lower bound was negative. Both ETH
regime lower bounds were also negative. The evidence therefore does not establish positive strategy
return across both lagged-volatility regimes in both development markets.

This rejection does not imply the high-volatility point estimates are false. It means the fixed
sample and dependence-aware uncertainty rule do not support the broader joint claim.

## Data and provenance

- Provider: OKX public spot market data;
- instruments: BTC-USDT and ETH-USDT;
- bar: `1Dutc`;
- OOS dates: 2020-01-11 through 2026-06-07 UTC;
- source workflow run: `29877892427`;
- source artifact: `8513672060` (`quant-research-378`);
- source artifact SHA-256: `7902fd0e653a446151188dc426386bfb8406d404a348aaf8be13a7671deb10ec`;
- tested merge commit: `fd8d2191e30bb0aeb80da0021f2923f3bc9a8377`;
- persistent source head: `e1f49e3ad33fa2cd820de5ca0a6f70231f214a20`;
- tested base: `a2f1ab460409113057198ebdd00e3ce4f6c7bf82`;
- BTC returns SHA-256: `539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73`;
- ETH returns SHA-256: `027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6`.

## Claim boundary

BTC and ETH are development markets. This is a descriptive mechanism diagnostic, not a new trading
rule, causal result, alpha claim, or untouched-holdout test. It does not model spread, market impact,
liquidity, capacity, latency, or partial fills.
