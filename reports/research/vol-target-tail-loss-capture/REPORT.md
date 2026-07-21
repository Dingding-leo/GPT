# Volatility-Targeted Benchmark Tail-Loss Capture

## Hypothesis

For both BTC-USDT and ETH-USDT, the strategy has a positive conditional mean return delta versus volatility-targeted long on that benchmark's worst-decile OOS days, with a 95% paired moving-block-bootstrap lower bound above zero.

Canonical signature: `vol-target-worst-decile-tail-delta-v1|markets=BTC-USDT,ETH-USDT|benchmark=vol-targeted-long|tail=0.10|metric=conditional-mean-return-delta|block=20|resamples=2000|confidence=0.95|seed=20260722|candidate_count=0`

## Economic rationale

The strategy combines directional timing with volatility-scaled long/cash exposure. If its lower-drawdown evidence reflects a genuine defensive mechanism rather than an aggregate-path artifact, it should lose materially less than a volatility-targeted long benchmark specifically during that benchmark's worst daily outcomes. The strongest falsifiable version requires a positive worst-decile conditional mean return delta with a serial-dependence-aware confidence interval above zero in both development markets.

## Fixed specification

- Development markets: `BTC-USDT` and `ETH-USDT` OKX spot `1Dutc`.
- Strategy and benchmark returns: persisted rolling OOS returns from the same workflow artifact.
- Comparator: `benchmark_volatility_targeted_long_return`.
- Tail definition: each market's worst `10%` benchmark-return observations.
- Primary statistic: mean `strategy_return - benchmark_return` conditional on the benchmark tail.
- Uncertainty: paired moving-block bootstrap, block length `20`, `2,000` resamples, `95%` interval, seed `20260722`.
- The benchmark tail threshold is recomputed inside each bootstrap resample.
- Joint support rule: the 95% lower bound must be strictly positive for both instruments.
- Candidate count: `0`; no alternate tail fractions, benchmarks, block lengths, support thresholds, or seeds were searched.

## Real-data provenance

- Source workflow run: `29841895366`.
- Source artifact: `8499721759` (`quant-research-51`).
- Source artifact SHA-256: `dbe25282321fa1d1fdafa2945c1a45e6a6481060d693956fd5fb3225b03f3fd7`.
- Source head: `4c02eccac3d6d81139c73d0b64bb5067756dac93`.
- OOS range: `2020-01-11` through `2026-06-07` UTC.
- Observations: `2,340` daily OOS rows per instrument.
- BTC returns SHA-256: `539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73`.
- ETH returns SHA-256: `027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6`.

The downloaded artifact archive and both return files were independently rehashed before analysis. Timestamps were parsed as UTC and required to be unique, strictly increasing, and exactly daily. No market values were generated or altered.

## Result

**Joint verdict: supported.**

| Instrument | Tail obs | Strategy mean | Benchmark mean | Observed delta | 95% CI | P(delta > 0) | Strategy beats benchmark |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 234 | -0.014016 | -0.045293 | 0.031277 | [0.026150, 0.036694] | 1.000 | 100.0% |
| ETH-USDT | 234 | -0.016234 | -0.048878 | 0.032644 | [0.026937, 0.037658] | 1.000 | 100.0% |

Both markets satisfy the predeclared support rule. The strategy still loses money on average during the benchmark's worst decile, but the loss is approximately 3.1–3.3 percentage points smaller per tail day than the volatility-targeted long comparator.

## Secondary upside-cost diagnostic

This diagnostic was predeclared as interpretation only and is not part of the support rule.

| Instrument | Best-decile strategy mean | Benchmark mean | Observed delta | 95% CI |
|---|---:|---:|---:|---:|
| BTC-USDT | 0.017444 | 0.048253 | -0.030809 | [-0.034783, -0.026477] |
| ETH-USDT | 0.017439 | 0.053742 | -0.036303 | [-0.039894, -0.031943] |

The same defensive profile gives up substantial return on the benchmark's best-decile days. This supports a risk-control interpretation rather than alpha or unconditional return superiority.

## Calculation and executed command

For each instrument, the analysis verified the file SHA-256 and daily chronology, selected tail observations from the persisted OOS return frame, and recomputed the tail threshold within each paired block-bootstrap resample. The executed analysis command was:

```bash
python /tmp/tail_loss_analysis.py
```

The exact machine-readable output is persisted beside this report as `result.json`.

## Interpretation

The fixed hypothesis is supported as evidence that the existing strategy reduces conditional losses during severe days relative to a volatility-targeted long benchmark in both BTC and ETH development markets. This does **not** establish alpha, higher Sharpe, higher Calmar, higher CAGR, capacity, executable slippage, or untouched-holdout validity.

## Limitations

- BTC-USDT and ETH-USDT are development markets, not untouched holdouts.
- Worst-decile membership is an ex-post evaluation label, not a tradable signal.
- The statistic concerns conditional daily means, not multi-day crash paths or recovery speed.
- The same artifact underlies prior drawdown and bootstrap investigations; this is a distinct predeclared diagnostic, not independent market evidence.
- No alternative tail fraction or comparator was tested in this run, so neighborhood robustness remains unresolved.
