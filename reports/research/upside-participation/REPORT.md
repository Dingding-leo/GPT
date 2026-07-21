# Upside-participation asymmetry diagnostic

## Hypothesis

For both BTC-USDT and ETH-USDT, the strategy's upside capture relative to the
volatility-targeted-long benchmark exceeds its downside capture. The hypothesis
passes only if the 95% paired moving-block-bootstrap lower bound for
`upside capture - downside capture` is positive in both development markets.

Canonical signature:

```text
upside-participation-asymmetry-v1|markets=BTC-USDT,ETH-USDT|benchmark=volatility-targeted-long|metric=upside-capture-minus-downside-capture|capture=conditional-arithmetic-mean-ratio|block=20|resamples=2000|confidence=0.95|seeds=BTC-USDT:20260722,ETH-USDT:20260723|candidate_count=1
```

## Economic rationale

A long/cash trend-and-risk-control strategy can lower drawdown simply by reducing
exposure, without distinguishing favourable from adverse benchmark sessions. A
positive participation asymmetry would support the stronger mechanism claim that
the strategy retains more benchmark upside than downside rather than merely
running at lower average risk.

## Fixed specification

- provider: OKX public spot market data;
- instruments: BTC-USDT and ETH-USDT development markets;
- bar: `1Dutc`;
- benchmark: volatility-targeted long;
- source workflow run: `29866245582`;
- source artifact: `8509324116` (`quant-research-306`);
- artifact SHA-256:
  `67e84186d26f3d5e1806d77be1c9ff3c4f9da8d041da12d63a40d00e79a42a4a`;
- source persistent head: `28d9911192806a045e27aef5512967ecb570d919`;
- source tested checkout: `a48afc549121678fb066899db67fe20faf2f5b30`;
- observations: 2,340 OOS daily returns per market, January 11, 2020 through
  June 7, 2026 UTC;
- paired moving-block resamples: 2,000 per market;
- block length: 20 days;
- confidence: 95%;
- seeds: 20260722 for BTC-USDT and 20260723 for ETH-USDT;
- candidates searched: one predeclared primary metric.

Capture is the conditional arithmetic mean strategy return divided by the
conditional arithmetic mean benchmark return. The benchmark's sign determines
the upside and downside day sets. This avoids changing the day classification in
response to the strategy being tested.

Return-file SHA-256 values:

- BTC-USDT:
  `539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73`;
- ETH-USDT:
  `027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6`.

## Results

| Market | Upside capture | Downside capture | Asymmetry | 95% interval | P(asymmetry > 0) |
|---|---:|---:|---:|---:|---:|
| BTC-USDT | 32.6226% | 30.8804% | +1.7422 pp | [-2.6675, +6.3203] pp | 77.90% |
| ETH-USDT | 31.1294% | 31.5136% | -0.3842 pp | [-4.6172, +3.4204] pp | 42.00% |

BTC-USDT had 1,191 positive and 1,149 negative benchmark observations. ETH-USDT
had 1,212 positive and 1,128 negative benchmark observations. Neither market had
a zero benchmark return in the persisted OOS series.

## Verdict: rejected

Neither market has a positive lower confidence bound, and ETH-USDT's point
estimate is slightly negative. The experiment therefore does not support a claim
that the strategy systematically preserves more benchmark upside than downside.
The previously recorded lower-drawdown evidence should continue to be described
as a lower-risk or lower-exposure effect unless stronger independent evidence is
obtained.

## Candidate accounting

Exactly one predeclared metric was tested. No alternative sign threshold,
compounding convention, benchmark, block length, seed, market, or subgroup was
searched after viewing the result. No strategy parameters, fees, execution delay,
folds, or sealed-holdout rules changed.

## Reproduction

```bash
python reports/research/upside-participation/analysis.py \
  --artifact-dir /path/to/quant-research-306/okx \
  --output /tmp/upside-participation.json

cmp /tmp/upside-participation.json \
  reports/research/upside-participation/result.json
```

## Limitations

Capture ratios are descriptive conditional-mean statistics and do not establish
causality or alpha. BTC-USDT and ETH-USDT are development markets, not untouched
holdouts. Moving-block resampling preserves local serial dependence but does not
model spread, slippage, market impact, capacity, or live execution. This result
does not alter the rejected sealed LTC-USDT verdict and does not justify same-
market retuning, leverage, or trading.
