# Volatility-matched drawdown diagnostic

## Verdict

**Rejected.** The existing walk-forward strategy does not retain a statistically supported maximum-drawdown advantage over the volatility-targeted-long benchmark after the strategy is scaled to the benchmark's realized daily volatility inside each paired moving-block resample.

This result narrows the prior defensive interpretation: lower observed drawdown may be explained materially by lower realized volatility rather than by a distinct path-timing advantage. It is not evidence of alpha, superior Sharpe, deployable leverage, or a tradable sizing rule.

## Predeclared hypothesis

For both BTC-USDT and ETH-USDT, after matching strategy daily volatility to the volatility-targeted-long benchmark within each paired moving-block sample, the maximum-drawdown reduction remains positive with a 95% lower confidence bound above zero.

Canonical signature:

```text
volatility-matched-drawdown-v1|markets=BTC-USDT,ETH-USDT|benchmark=volatility-targeted-long|metric=max-drawdown-reduction|scale=recomputed-per-resample|block=20|resamples=2000|confidence=0.95|seeds=BTC-USDT:20260722,ETH-USDT:20260723|candidate_count=0
```

Candidate count: **0**. No alternative benchmark, scaling rule, block length, confidence level, seed, acceptance threshold, or market subset was searched after observing the result.

## Economic rationale

The strategy's original OOS returns have substantially lower daily volatility than the volatility-targeted-long benchmark. A lower-volatility series will normally exhibit a smaller drawdown even without superior timing. Volatility matching is therefore a diagnostic intended to separate a path-shape effect from simple de-risking.

For each observed or resampled sequence:

1. calculate population daily volatility for the strategy and benchmark;
2. scale strategy returns by `benchmark_volatility / strategy_volatility`;
3. compute maximum drawdown from initial capital for both series;
4. define drawdown reduction as `abs(benchmark_mdd) - abs(scaled_strategy_mdd)`.

The scaling factor is recomputed inside every bootstrap resample. This avoids applying a full-sample fixed scale to all resampled paths. The diagnostic is ex-post and is not a deployable portfolio-sizing rule.

## Data and research boundary

- Provider: OKX public market data
- Instruments: BTC-USDT and ETH-USDT spot
- Bar: `1Dutc`
- Market status: development markets, not untouched holdouts
- Source workflow run: `29841895366`
- Source artifact: `8499721759` (`quant-research-51`)
- Source artifact SHA-256: `dbe25282321fa1d1fdafa2945c1a45e6a6481060d693956fd5fb3225b03f3fd7`
- Source code head: `4c02eccac3d6d81139c73d0b64bb5067756dac93`
- BTC returns SHA-256: `539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73`
- ETH returns SHA-256: `027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6`
- Observations: 2,340 daily OOS rows per market
- Period: 2020-01-11 through 2026-06-07 UTC

The analysis validates the return-file hashes, explicit timezone information, uniqueness, strict ordering, exact daily cadence, finite numeric returns, and returns greater than `-1` before calculation.

## Fixed inference specification

- Paired moving-block bootstrap without circular wrapping
- Block length: 20 observations
- Resamples: 2,000 per market
- Confidence interval: 95%
- BTC seed: 20260722
- ETH seed: 20260723
- Scale recomputed inside each resample
- Joint acceptance: the 95% lower bound for drawdown reduction must be above zero in both markets

## Results

| Market | Full-sample scale | Benchmark MDD | Vol-matched strategy MDD | Point DD reduction | Bootstrap median | 95% interval | P(reduction > 0) |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 2.101838 | -0.720560 | -0.530889 | +0.189672 | +0.025906 | [-0.222420, +0.272058] | 0.5985 |
| ETH-USDT | 2.109730 | -0.659917 | -0.537716 | +0.122201 | -0.042974 | [-0.300109, +0.213786] | 0.3645 |

The original-sequence point estimate is positive in both markets, but both confidence intervals cross zero. ETH's bootstrap median is negative. The predeclared joint hypothesis is therefore rejected.

## Candidate accounting and failure reasons

No candidates were searched. The only fixed hypothesis failed because:

- BTC-USDT 95% lower bound: `-0.222420`, not above zero;
- ETH-USDT 95% lower bound: `-0.300109`, not above zero;
- joint acceptance requires both markets to pass.

No same-market retuning or alternate specification was attempted.

## Reproduction

After downloading and extracting artifact `8499721759` so that the extracted `okx` directory contains each market's `walk_forward_returns.csv`:

```bash
python reports/research/volatility-matched-drawdown/analysis.py \
  --artifact-dir /path/to/extracted/okx \
  --output /tmp/volatility-matched-drawdown.json

cmp \
  /tmp/volatility-matched-drawdown.json \
  reports/research/volatility-matched-drawdown/result.json
```

Commands executed for this report:

```bash
sha256sum \
  /mnt/data/quant-research-51.zip \
  /tmp/qr51/okx/BTC-USDT/walk_forward_returns.csv \
  /tmp/qr51/okx/ETH-USDT/walk_forward_returns.csv

python reports/research/volatility-matched-drawdown/analysis.py \
  --artifact-dir /tmp/qr51/okx \
  --output /tmp/recomputed.json

cmp -s /tmp/recomputed.json \
  reports/research/volatility-matched-drawdown/result.json

python -m py_compile \
  reports/research/volatility-matched-drawdown/analysis.py

python -m json.tool \
  reports/research/volatility-matched-drawdown/result.json
```

Observed outcomes before opening the PR:

- source artifact and both returns-file hashes matched;
- deterministic result comparison passed;
- Python compilation passed;
- JSON validation passed.

## Limitations

- BTC-USDT and ETH-USDT are development markets previously used for architecture and research decisions.
- Volatility matching is an ex-post diagnostic, not a feasible real-time leverage policy.
- Maximum drawdown is path-dependent; moving-block resampling preserves dependence within blocks but concatenates blocks into new paths.
- Only the predeclared 20-day block specification was tested. No block-length neighborhood was searched because that would create a new family of post-result tests.
- This report does not supersede the prior observation that the unscaled strategy had lower realized drawdown. It rejects the stronger claim that the advantage remains statistically supported after volatility normalization.

## Next research task

Apply the already frozen strategy and acceptance rules to the first previously unused sealed OKX spot market only after the architecture and threshold version is committed, without same-market retuning.
