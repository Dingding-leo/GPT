# Information ratio versus volatility-targeted long

## Hypothesis

BTC-USDT and ETH-USDT net rolling out-of-sample strategy returns have a positive annualized information ratio versus the persisted volatility-targeted-long benchmark.

The joint hypothesis passes only if the 95% paired moving-block-bootstrap lower bound for the information ratio is strictly positive in both development markets.

Canonical signature:

```text
information-ratio-vs-volatility-benchmark-v1|markets=BTC-USDT,ETH-USDT|source=persisted-net-rolling-oos-returns|benchmark=volatility-targeted-long|active-return=strategy-return-minus-benchmark-return|metric=annualized-information-ratio-mean-active-return-over-sample-tracking-error|annualization=365|claim=information-ratio>0-in-both-markets|resampling=paired-noncircular-moving-block-bootstrap|block-length=20-sessions|resamples=2000|confidence=0.95|seeds=BTC-USDT:2026072315,ETH-USDT:2026072316|candidate_count=1
```

## Economic rationale and overlap audit

Separate Sharpe, Sortino, Omega, and drawdown ratios can favor a defensive strategy even when it does not add positive return relative to a risk-control benchmark. Information ratio tests the paired active-return process directly: average strategy-minus-benchmark return per unit of tracking error.

Current `main`, README, Phase 2 and Phase 3 protocol issues, research ledger #21, recent commits, open issues, all open research pull requests, existing reports, and canonical signatures were inspected before this experiment. Existing research covers absolute and downside risk ratios, drawdown paths, fold concentration, execution delay, parameter selection, portfolio risk, and turnover efficiency. No existing issue, branch, report, or pull request tested active-return information ratio versus volatility-targeted long.

Exactly one joint candidate was tested. No alternate benchmark, active-return definition, tracking-error convention, annualization, block length, resample count, seed, market subset, fee, delay, fold definition, or acceptance threshold was selected after observing the result.

## Fixed method

- Provider and market type: OKX public spot data.
- Markets: BTC-USDT and ETH-USDT development markets.
- Bar: `1Dutc`.
- OOS period: 2020-01-11 through 2026-06-07 UTC.
- Observations: 2,340 per market.
- Active return: persisted net strategy return minus persisted net volatility-targeted-long return on the same timestamp.
- Information ratio: `sqrt(365) * mean(active return) / sample_std(active return)`.
- Uncertainty: paired non-circular 20-session moving blocks over strategy and benchmark returns.
- Resamples: 2,000.
- Confidence: 95%.
- Existing one-bar execution delay, 10-bps costs, 730-session selection windows, 90-session OOS folds, and 27-candidate search remain unchanged.

## Results

| Market | Annualized active return | Annualized tracking error | Information ratio | 95% interval | P(IR > 0) |
|---|---:|---:|---:|---:|---:|
| BTC-USDT | -19.266773% | 38.055963% | -0.506275 | -1.392749 to +0.284264 | 10.45% |
| ETH-USDT | -34.473121% | 40.644669% | -0.848158 | -1.772220 to -0.044162 | 1.90% |

Both point estimates were negative. Neither lower confidence bound was positive, and the ETH interval was entirely below zero.

## Verdict

**Rejected.**

```text
searched: 1
passed:   0
rejected: 1
```

The adaptive strategy does not demonstrate positive active-return efficiency relative to volatility-targeted long on the current development evidence. This does not establish that the benchmark is deployable; it establishes that the strategy has not earned a positive paired information ratio over it under the fixed specification.

## Provenance

- Source workflow: `29957899078`.
- Source artifact: `8544795485` (`quant-research-source-1374-attempt-1`).
- Source artifact SHA-256: `a4177288bba8a1599576688d8481546149512e96ad149c7b91f2e6f00d71fd31`.
- Source head: `160fb816405deebbd142289f5fbefb8e5d403646`.
- BTC return-file SHA-256: `539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73`.
- ETH return-file SHA-256: `027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6`.

## Reproduction

```bash
sha256sum /mnt/data/quant-research-source-182.zip
unzip -q /mnt/data/quant-research-source-182.zip -d /tmp/qr182

python reports/research/information-ratio-vs-volatility-benchmark/analysis.py \
  --artifact-dir /tmp/qr182 \
  --output /tmp/recomputed-information-ratio.json

cmp -s \
  /tmp/recomputed-information-ratio.json \
  reports/research/information-ratio-vs-volatility-benchmark/result.json

python -m py_compile \
  reports/research/information-ratio-vs-volatility-benchmark/analysis.py \
  tests/test_information_ratio_vs_volatility_benchmark_report.py

pytest -q tests/test_information_ratio_vs_volatility_benchmark_report.py
python -m json.tool \
  reports/research/information-ratio-vs-volatility-benchmark/result.json
```

## Limitations

BTC and ETH remain development markets rather than untouched holdouts. Moving-block concatenation creates artificial joins and preserves dependence only within 20-session blocks. Information ratio is sensitive to the chosen benchmark and sample tracking-error convention. Spread, nonlinear impact, capacity, latency, and partial fills remain unmodeled beyond persisted transaction costs.
