# Turnover efficiency versus volatility-targeted long

## Hypothesis

BTC-USDT and ETH-USDT net rolling out-of-sample strategy returns have higher net arithmetic return per unit of absolute position turnover than the persisted volatility-targeted-long benchmark.

The joint hypothesis passes only if the 95% paired moving-block-bootstrap lower bound for

```text
strategy return per turnover - benchmark return per turnover
```

is strictly positive in both development markets.

Canonical signature:

```text
turnover-efficiency-vs-volatility-benchmark-v1|markets=BTC-USDT,ETH-USDT|source=persisted-net-rolling-oos-returns-and-turnover-plus-immutable-snapshot|benchmark=volatility-targeted-long-reconstructed-from-snapshot|metric=net-arithmetic-return-sum/absolute-position-turnover-sum|claim=strategy-minus-benchmark-return-per-turnover>0-in-both-markets|resampling=paired-four-column-noncircular-moving-block-bootstrap|block-length=20-sessions|resamples=2000|confidence=0.95|seeds=BTC-USDT:2026072311,ETH-USDT:2026072312|candidate_count=1
```

## Economic rationale and overlap audit

The adaptive process changes exposure substantially more often than the volatility-targeted-long benchmark. A strategy that adds selection complexity and trading burden should earn more net return for each unit of absolute position change if that activity is economically efficient.

Current `main`, README, Phase 2 and Phase 3 protocol issues, research ledger #21, recent commits, open issues, all open research pull requests, CI evidence, and prior canonical signatures were inspected before this experiment. Existing work covers aggregate return and risk metrics, concentrated slippage, exposure timing, execution delay, fold concentration, adaptive-versus-fixed performance, Sortino, Omega, Ulcer Index, and volatility-matched drawdown. No existing issue, branch, report, or pull request tested net return per unit turnover against volatility-targeted long.

Exactly one joint candidate was tested. No alternate benchmark, turnover convention, return convention, block length, resample count, seed, market subset, fee, execution delay, fold definition, or acceptance threshold was selected after observing the result.

## Fixed method

- Provider and market type: OKX public spot data.
- Markets: BTC-USDT and ETH-USDT development markets.
- Bar: `1Dutc`.
- OOS period: 2020-01-11 through 2026-06-07 UTC.
- Observations: 2,340 per market.
- Strategy returns and turnover: persisted rolling OOS columns after the repository's one-bar execution delay and 10-bps turnover cost.
- Benchmark: independently reconstructed volatility-targeted long using a 30-session log-return volatility estimate, 50% annual target, maximum position 1, one-session delay, 365-day annualization, 10-bps turnover cost, and cash entry at the OOS boundary.
- Benchmark validation: reconstructed returns had to match the persisted benchmark-return column within `5e-15` before inference.
- Efficiency metric: `sum(net daily arithmetic returns) / sum(absolute position turnover)`.
- Uncertainty: paired non-circular 20-session moving blocks over strategy return, strategy turnover, benchmark return, and benchmark turnover.
- Resamples: 2,000.
- Confidence: 95%.

## Results

| Market | Strategy total turnover | Benchmark total turnover | Strategy return / turnover | Benchmark return / turnover | Delta | 95% interval | P(delta > 0) |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 101.078918 | 25.488121 | 0.010889 | 0.091646 | -0.080756 | -0.193591 to +0.010991 | 4.20% |
| ETH-USDT | 104.261699 | 33.702391 | 0.008427 | 0.091644 | -0.083217 | -0.179028 to -0.009638 | 1.45% |

The strategy generated only about `0.0109` and `0.0084` units of net arithmetic return per unit of absolute turnover in BTC and ETH, respectively, compared with about `0.0916` for volatility-targeted long in both markets. Both point deltas were negative. Neither lower confidence bound was positive, and the ETH interval was entirely negative.

## Verdict

**Rejected.**

Candidate accounting:

```text
searched: 1
passed:   0
rejected: 1
```

The adaptive strategy does not demonstrate superior net return per unit turnover versus volatility-targeted long on the current development evidence. This is an execution-efficiency finding, not a claim that turnover itself is harmful or that the benchmark is deployable without further liquidity and capacity analysis.

## Provenance

- Source workflow: `29953609625`.
- Source artifact: `8543136580` (`quant-research-source-1333-attempt-1`).
- Source artifact SHA-256: `88f5457a66e756384386a9f9712b029bcefbb2335f881f17a75200180b071414`.
- Source head: `4c484bddb670ca58c131ff55fbf1b176389abe62`.
- BTC return-file SHA-256: `539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73`.
- BTC snapshot SHA-256: `b0bd7c6c7e30fcc095073169f60bde24559f481b24cc6f4bdfb85349f57974bb`.
- ETH return-file SHA-256: `027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6`.
- ETH snapshot SHA-256: `78f3bf81d3983e6c894066a1c298fbf14ae06a5eff9ca7326554b0a8933c0df5`.

## Reproduction

```bash
sha256sum /mnt/data/quant-research-source-174.zip
unzip -q /mnt/data/quant-research-source-174.zip -d /tmp/qr174

python reports/research/turnover-efficiency-vs-volatility-benchmark/analysis.py \
  --artifact-dir /tmp/qr174 \
  --output /tmp/recomputed-turnover-efficiency.json

cmp -s \
  /tmp/recomputed-turnover-efficiency.json \
  reports/research/turnover-efficiency-vs-volatility-benchmark/result.json

python -m py_compile \
  reports/research/turnover-efficiency-vs-volatility-benchmark/analysis.py \
  tests/test_turnover_efficiency_vs_volatility_benchmark_report.py

pytest -q tests/test_turnover_efficiency_vs_volatility_benchmark_report.py
python -m json.tool \
  reports/research/turnover-efficiency-vs-volatility-benchmark/result.json
```

## Limitations

BTC and ETH remain development markets rather than untouched holdouts. The ratio uses summed arithmetic returns rather than a continuous-capital profit attribution, and a unit of absolute turnover is not the same as a completed round trip. Moving-block resampling preserves paired observed rows and within-block ordering but introduces artificial joins. The analysis includes the repository's linear 10-bps cost but does not model spread, nonlinear market impact, capacity, latency, or partial fills.
