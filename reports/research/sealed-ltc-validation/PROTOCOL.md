# Sealed LTC-USDT validation protocol

## Status before data access

This protocol freezes the test before any `LTC-USDT` market observations or results are downloaded or viewed for this experiment. Repository code search found no prior `LTC-USDT` research, report, branch, issue, or pull request.

## Falsifiable hypothesis

The frozen V2 walk-forward architecture will generalise to the previously unused OKX `LTC-USDT` spot market at `1Dutc` frequency. The joint hypothesis is supported only if both conditions hold:

1. the repository's unchanged robustness classifier returns a non-reject classification (`provisional alpha candidate` or `provisional risk-control candidate`); and
2. a paired 20-day moving-block bootstrap with 2,000 resamples and 95% confidence finds the strategy's maximum-drawdown delta versus the volatility-targeted-long benchmark has a lower confidence bound above zero.

Failure of either condition rejects the joint hypothesis. The sealed result must not trigger same-market retuning.

Canonical signature:

`sealed-market-v2-v1|provider=OKX|market_type=spot|market=LTC-USDT|bar=1Dutc|start=2017-01-01|code=29c28c1031bddda6c5e42f2672aaa6adaa004cad|config_sha256=992ed2f5ea53cd3704cdfc876c1f464b0c618590aface911d781421f672398c5|selection_bars=730|test_bars=90|grid=3x3x3|transaction_cost_bps=10|execution_delay=1bar|benchmark=volatility-targeted-long|metric=max_drawdown_delta|block=20|resamples=2000|confidence=0.95|seed=20260722|accept=repository_nonreject_and_ci_lower_gt_0`

## Frozen implementation and parameters

- base commit: `29c28c1031bddda6c5e42f2672aaa6adaa004cad`;
- configuration: `config/okx_research.json`;
- configuration SHA-256: `992ed2f5ea53cd3704cdfc876c1f464b0c618590aface911d781421f672398c5`;
- public provider endpoint: OKX `GET /api/v5/market/history-candles`;
- instrument: `LTC-USDT` spot;
- bar: `1Dutc`;
- requested start: `2017-01-01`;
- only confirmed candles (`confirm=1`);
- long/cash only, maximum position `1.0`, minimum position `0.0`;
- transaction cost: 10 bps per unit turnover;
- signal execution delay: one bar;
- selection window: 730 bars;
- non-overlapping test window: 90 bars;
- candidate grid: momentum `{30, 90, 180}` × reversal `{2, 5, 10}` × trend weight `{0.55, 0.70, 0.85}` = 27 candidates per fold;
- cost multipliers: `1x`, `2x`, `4x`;
- parameter perturbations: repository defaults, unchanged;
- bootstrap: paired moving blocks, block length 20, 2,000 resamples, 95% confidence, seed `20260722`, annualisation 365.

## Execution sequence

1. Commit this protocol.
2. Download the single declared market once through the existing public-data pipeline.
3. Persist raw pages, normalized OHLCV, metadata, SHA-256 hashes, walk-forward outputs, and experiment manifest.
4. Run the fixed bootstrap diagnostic against the persisted walk-forward returns.
5. Record every fold's 27-candidate search, all robustness failures, the joint verdict, and exact commands.
6. Do not alter the market, grid, fees, execution delay, thresholds, bootstrap settings, or acceptance rule after viewing the result.

## Interpretation limits

This is one sealed-market validation of the already-developed architecture, not evidence of universal generalisation. A positive outcome does not establish capacity, live execution quality, or alpha. A rejection remains a valid result and must be retained.