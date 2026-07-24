# Adaptive Rolling Selection Risk Versus the Fixed Base Configuration

## Hypothesis

The repository's adaptive 730-bar selection / 90-bar test process improves both maximum
drawdown and Calmar versus the ex ante fixed base configuration in BTC-USDT and ETH-USDT.

Economic rationale: the 27-candidate adaptive search may still be defensible as a risk-control
layer even when its incremental mean-return and Sharpe value is unproven. It should receive
that interpretation only if its drawdown and Calmar improvements are reliable relative to the
already-declared fixed base configuration.

## Predeclared method

- Markets: OKX spot BTC-USDT and ETH-USDT `1Dutc`; development evidence only.
- Evaluation: 2,340 persisted net OOS observations per market from 2020-01-11 through
  2026-06-07 UTC.
- Adaptive path: the repository's complete 27-candidate rolling selection process.
- Fixed comparator: momentum 90, reversal 5, trend weight 0.70, volatility lookback 30,
  target volatility 0.50, long/cash, one-bar execution delay, and 10 bps per unit turnover.
- The fixed path is continuous and is not reset at fold boundaries.
- Metrics: adaptive-minus-fixed maximum-drawdown delta and Calmar delta. Maximum drawdown
  is negative, so a positive delta means the adaptive path had a shallower drawdown.
- Uncertainty: 2,000 paired non-circular moving-block resamples with 20-session blocks,
  95% confidence, and fixed market-specific seeds.
- Pass rule: both 95% lower bounds must be strictly positive in both markets.

Exactly one joint hypothesis was tested. No alternate comparator, metric, block length, seed,
market subset, cost, delay, or threshold was selected after observing the result.

## Results

| Market | Adaptive MDD | Fixed MDD | MDD delta (95% interval) | Adaptive Calmar | Fixed Calmar | Calmar delta (95% interval) |
|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | -29.098358% | -35.802532% | +6.704174% [-13.281428%, +19.946146%] | 0.531504 | 0.309114 | +0.222390 [-0.464113, +0.866740] |
| ETH-USDT | -27.917448% | -28.517837% | +0.600389% [-24.868168%, +14.940518%] | 0.395178 | 0.471007 | -0.075829 [-0.865490, +0.518313] |

Both point drawdowns are slightly shallower under adaptive selection, and BTC's point Calmar
is higher. However, every confidence interval crosses zero, while ETH's point Calmar is lower
than the fixed base. The joint hypothesis is therefore **rejected**. The evidence does not
establish that adaptive rolling selection adds reliable drawdown or Calmar value over the fixed
base configuration.

This result does not prove that adaptive selection should be removed. It limits the supported
interpretation: its incremental risk-control benefit remains unproven on the current development
markets.

## Candidate accounting

- Joint hypotheses searched: 1.
- Supported: 0.
- Rejected: 1.
- Fixed comparators searched: 1, the pre-existing repository base configuration.

Canonical signature:

`adaptive-selection-risk-vs-fixed-base-v1|markets=BTC-USDT,ETH-USDT|source=immutable-OKX-1Dutc-snapshots-and-persisted-net-rolling-oos-returns|adaptive=repository-730-selection-90-test-27-grid|fixed-base=momentum90-reversal5-trend0.70-vol30-targetvol0.50-long-cash|execution=one-bar-delay-10bps-continuous-position|evaluation=2020-01-11..2026-06-07-2340-bars|metrics=adaptive-minus-fixed-max-drawdown,calmar|max-drawdown-delta=adaptive-negative-drawdown-minus-fixed-negative-drawdown|resampling=paired-noncircular-moving-block-bootstrap-20|resamples=2000|confidence=0.95|pass=both-metric-lower-bounds-positive-in-both-markets|candidate_count=1`

## Provenance

- Source workflow: `29922259536`.
- Source artifact: `8530429665`, `quant-research-source-1027-attempt-1`.
- Source artifact SHA-256:
  `da7ab1b69654f50d0da42e2898a69780269e797bcc808dfdaf1f4e04ae9b64df`.
- Source head: `d2249852a0236398bd540b0e9960009ada7e6940`.
- Source base: `1302c649cf87a7eaf04cbd442a33573cd939e2b4`.
- Exact snapshot, report, and return-file hashes are recorded in `result.json`.

## Reproduction

```bash
sha256sum /path/to/quant-research-source-1027-attempt-1.zip
unzip -q /path/to/quant-research-source-1027-attempt-1.zip -d /tmp/qr1027

python reports/research/adaptive-selection-risk-vs-fixed-base/analysis.py \
  --artifact-dir /tmp/qr1027 \
  --output /tmp/recomputed-adaptive-risk.json

cmp -s \
  /tmp/recomputed-adaptive-risk.json \
  reports/research/adaptive-selection-risk-vs-fixed-base/result.json
```

## Limitations

BTC and ETH are development markets, not untouched holdouts. Moving-block concatenation
creates artificial joins for path-dependent drawdown and Calmar calculations. The comparator
is the repository's existing fixed base, not an exhaustively selected fixed candidate. Spread,
market impact, liquidity, capacity, latency, and partial fills remain unmodeled.
