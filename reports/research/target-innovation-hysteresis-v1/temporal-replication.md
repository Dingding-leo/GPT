# Target-Innovation Hysteresis v1 — Temporal Replication

## Classification

`replicated_as_development_only_turnover_suppression_overlay`

This is a development-only temporal replication of the already-frozen H1 policy. It does not inspect any untouched market, nominate a selector, or promote the rejected base Alpha.

Policy SHA-256: `437868cc0b2a166cf9b9a3f7dd28848a25664b567a9a6857c333108a3eb7fcf1`

Payload SHA-256: `6aa14ddcea71d0ffd5e1647e1d7e2e313aa67ae1b3f9f1848beb894c483d10ee`

## Fixed universe and sample

- Markets fixed for this replication: BTC-USDT and ETH-USDT only.
- No market was removed after results.
- Source workflow: `30347175588` at `d7cc15839755484b682d6e9094298b8a32f70230`.
- 25,920 hourly OOS observations and 12 fixed 2,160-hour folds per market.
- Exact 5 bps one-way fee on absolute position adjustment.
- Chronological replication blocks: folds 1-6 and folds 7-12.

Untouched cross-asset markets were not inspected because issue #536 has not nominated a selector policy.

## Replication result

| Market | Half | H0 return | H1 return | H0 Sharpe | H1 Sharpe | H0 turnover | H1 turnover | Break-even fee |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | folds 1-6 | 54.29% | 55.52% | 1.088 | 1.105 | 37.10 | 24.70 | 0.678 bps |
| BTC-USDT | folds 7-12 | -6.93% | -5.88% | -0.396 | -0.326 | 53.35 | 36.60 | 0.478 bps |
| ETH-USDT | folds 1-6 | -8.19% | -5.59% | -0.113 | -0.036 | 67.59 | 47.21 | -4.269 bps |
| ETH-USDT | folds 7-12 | 26.69% | 28.29% | 0.935 | 0.979 | 57.18 | 44.18 | -1.555 bps |

H1 improves net return and Sharpe in all four fixed market-half replications. Paired 168-hour within-fold bootstrap intervals for the annualized mean and Sharpe improvements are positive in all four blocks. Holm-adjusted diagnostic probabilities remain below 0.0012, but these halves were not part of the original confirmatory family and are not described as untouched confirmation.

## Fold breadth and mechanism

- Positive net improvement: 20 of 23 nonzero market-fold comparisons.
- BTC: 10 of 11 nonzero folds improve; gross return improves in 5 of 12 folds.
- ETH: 10 of 12 folds improve; gross return improves in 9 of 12 folds.
- BTC early/late implied break-even fees are below 0.7 bps, well below the fixed 5 bps model. Its benefit is principally transaction-cost suppression.
- ETH improves gross as well as net return in both chronological halves.

Zero-turnover or zero-difference folds remain in the artifact and are not converted into finite break-even values.

## Pooled and worst-market interpretation

The equal-weight BTC/ETH series is a statistical summary only, not a cross-sectional portfolio rule. H1 improves pooled full-period return from 30.89% to 34.85%, Sharpe from 0.542 to 0.590, and annualized turnover from 53.80 to 38.17.

The overlay remains downstream of selector qualification. Overall residual Sharpe versus simple trend remains negative:

- BTC: -0.818 to -0.785.
- ETH: -0.587 to -0.546.

Therefore H1 is replicated as a candidate-neutral turnover overlay, but the base strategy remains rejected for promotion.

## Next strategy step

Merge the selector training-evidence dependency, run the single frozen selector comparison, nominate one policy, and then apply this exact H1 policy hash unchanged to the reserved untouched/prospective replication cohort.
