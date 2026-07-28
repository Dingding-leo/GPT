# Selector protocol v1 — frozen BTC/ETH development comparison

## Verdict

`selector_family_rejected_no_policy_qualifies`

The frozen S0–S5 comparison was run exactly once after the complete 27-candidate training-only evidence was published on this branch. No policy qualifies for nomination. No untouched market or prospective period was inspected.

## Protocol

- Markets: `BTC-USDT`, `ETH-USDT`, evaluated independently under the identical rule.
- Bar: confirmed public `1H` data only.
- Candidate grid: `3 × 3 × 3 = 27` frozen configurations.
- Selection window: `17,520H`.
- Test window: `2,160H`, 12 non-overlapping folds per market.
- OOS interval: `2023-07-24 00:00 UTC` through `2026-07-07 23:00 UTC`.
- Modeled exchange fee: exactly `5 bps` one-way on absolute turnover.
- Candidate-fold evaluations: `648`.
- Policy-fold evaluations: `144`.

Policies:

- `S0`: fold-local training-score argmax.
- `S1`: fixed centre configuration; no fold-local selection.
- `S2`: median target across the frozen one-coordinate neighbourhood of S0.
- `S3`: candidate with the highest causal mean percentile rank through the current training fold.
- `S4`: retain the previous candidate while it remains in the current training top two; otherwise switch to S0.
- `S5`: equal target average across candidates with positive training return and positive training Sharpe; cash if none qualify.

## Publication ordering

The complete training evidence was published before the official OOS comparison:

- BTC evidence publication commit: `ea5dfc91074662dec531ee67ae586fd9ca4b21e6`
- ETH evidence publication head: `0539cf09ed0b57e77f88cb09a059c4638e6e1dde`
- Official OOS result commit: `4b98ff134cc00df6bed580e045eb5f190011a5bd`
- Confirmatory-method repair commit: `823ede521dc7542502f5ae0c5ca139a222a822e8`

The `.b64` evidence files decode as follows:

```bash
base64 --decode BTC-USDT.training-evidence.jsonl.gz.b64 \
  | gzip --decompress > BTC-USDT.training-evidence.jsonl
base64 --decode ETH-USDT.training-evidence.jsonl.gz.b64 \
  | gzip --decompress > ETH-USDT.training-evidence.jsonl
base64 --decode selector-protocol-v1-oos-comparison.json.gz.b64 \
  | gzip --decompress > selector-protocol-v1-oos-comparison.json
```

SHA-256:

```text
BTC training JSONL  43dd6400d55a72c08fd63b545ff4f77c18af245e75e3952453ddeef4f3572348
BTC gzip            ce5f17f2e67d508bc312b6b3b0ffcce1e323309aad8f3cb9b236a8047300e822
ETH training JSONL  46a7ba551162498fc1b69a13f85ad0ad4c17d2c9f9413923c89b96dd10129155
ETH gzip            b1f6e5539970c7ae6f916d55cd7505377eade5b5a364b051efda777040469bf2
Official result     8ffb4b2e267fa80379e01aade5d68f1ef0395cb876d98d4eb4463eddbe1eeb71
Method repair       9b3da2df081a953ac502b5017dbe7c9c40840401af6a714ba98983a5beb68cc0
```

The strategy metrics and policy definitions in the official result are unchanged. Its original `confirmatory` section is superseded by `confirmatory-method-repair.json` because Issue #536 freezes Holm correction across ten **alternative-market comparisons**, rather than ten worst-market endpoint tests.

## Results

### BTC-USDT

| Policy | Net return | Sharpe | Annual turnover | Net edge/turnover | Profitable folds | Largest positive-fold share | Residual Sharpe vs trend |
|---|---:|---:|---:|---:|---:|---:|---:|
| S0 | 43.59% | 0.637 | 45.23 | 33.18 bps | 4/12 | 59.55% | -0.818 |
| S1 | 20.41% | 0.398 | 73.26 | 11.80 bps | 6/12 | 32.68% | -1.215 |
| S2 | 34.41% | 0.554 | 58.24 | 21.59 bps | 4/12 | 55.04% | -0.956 |
| S3 | 28.06% | 0.449 | 42.66 | 27.74 bps | 4/12 | 57.07% | -0.939 |
| S4 | 43.59% | 0.637 | 45.23 | 33.18 bps | 4/12 | 59.55% | -0.818 |
| S5 | 13.47% | 0.332 | 55.75 | 10.40 bps | 3/12 | 59.23% | -1.120 |

### ETH-USDT

| Policy | Net return | Sharpe | Annual turnover | Net edge/turnover | Profitable folds | Largest positive-fold share | Residual Sharpe vs trend |
|---|---:|---:|---:|---:|---:|---:|---:|
| S0 | 16.31% | 0.342 | 62.38 | 12.05 bps | 5/12 | 37.40% | -0.587 |
| S1 | 13.83% | 0.306 | 60.75 | 11.50 bps | 6/12 | 32.79% | -0.740 |
| S2 | 12.85% | 0.300 | 66.28 | 9.48 bps | 5/12 | 36.22% | -0.632 |
| S3 | -2.16% | 0.066 | 67.49 | 1.99 bps | 3/12 | 42.58% | -0.710 |
| S4 | 7.28% | 0.218 | 64.55 | 7.37 bps | 4/12 | 41.86% | -0.662 |
| S5 | 16.36% | 0.371 | 55.84 | 12.17 bps | 6/12 | 31.11% | -0.619 |

## Confirmatory uncertainty — repaired to the frozen multiplicity contract

Paired bootstrap contract:

- 5,000 resamples;
- 168H non-circular moving blocks within each fold;
- the fold boundary row is retained exactly once;
- identical resampling indices across policies and markets;
- seed `20260728`;
- one intersection-union test per alternative-market pair;
- each comparison requires both Sharpe delta `> 0` and net edge-per-turnover delta `> 0`;
- Holm correction across the exact ten comparisons frozen in Issue #536: five alternatives × two markets.

The first inference pass incorrectly applied Holm correction to ten worst-market endpoint tests. This was detected during review and repaired without changing any policy, position, return, fee, fold, data window, or OOS result. The complete corrected statistics are in `confirmatory-method-repair.json`.

All ten adjusted joint p-values are `1.0`. The only market-policy pair with both observed deltas above zero is ETH S5:

```text
ETH S5 Sharpe delta              +0.02892
Sharpe one-sided 95% lower       -0.44499
ETH S5 edge delta                +0.12812 bps
Edge one-sided 95% lower         -16.58812 bps
Joint raw p                       0.57848
Holm-adjusted joint p             1.00000
```

It therefore fails confirmatory inference, and S5 simultaneously performs materially worse than S0 on BTC.

Closest structurally robust alternative, S2:

```text
BTC Sharpe delta                 -0.08323
BTC Sharpe basic 95% interval    [-0.23194, -0.00976]
BTC edge delta                   -11.58352 bps
BTC edge basic 95% interval      [-28.14730, +3.17686] bps

ETH Sharpe delta                 -0.04258
ETH Sharpe basic 95% interval    [-0.31762, +0.18838]
ETH edge delta                   -2.57132 bps
ETH edge basic 95% interval      [-12.94175, +8.71643] bps
```

S4 demonstrates that the frozen top-two persistence rule does not repair the selector: it is identical to S0 on BTC and reduces ETH Sharpe by `0.12444` and edge per turnover by `4.67454 bps`.

## Statistical limits

- Deflated Sharpe was not computed because the repository-wide count of independent architecture families is incomplete. The gate therefore fails closed.
- CSCV/PBO was not reported because the predeclared promotion statistic is a paired hourly market-specific Sharpe and edge-per-turnover comparison; a fold-only CSCV ranking would not implement that frozen decision statistic.

## Decision

No selector policy is nominated. S0 remains rejected for promotion, and none of S1–S5 improves Sharpe and net edge per turnover in both markets while meeting breadth and concentration gates. The correct next strategy step is a materially orthogonal temporal architecture or information source, not another selector rescue on this consumed BTC/ETH development window.
