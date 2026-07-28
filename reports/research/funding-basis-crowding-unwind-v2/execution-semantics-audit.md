# Funding/basis execution-semantics audit

## Verdict

`rejected_after_execution_semantics_repair`

The immutable artifact from PR #568 reproduces the legacy close-to-close core exactly, despite the PR report describing observed next-open-to-next-open accounting. Reconstructing the intended next-open path from the artifact's 132 exact public OKX responses modestly worsens F1 in both BTC and ETH and leaves the family deterministically rejected.

## Frozen experiment

- Family: `funding-basis-crowding-unwind-v2`
- Candidates: F0 funding-only attribution; F1 strict funding/basis unwind
- Markets: BTC-USDT and ETH-USDT independently
- Sample: 2026-05-08 18:00 UTC through 2026-07-17 17:00 UTC
- Observations: 1,680 per market; 5 non-overlapping 336H folds
- Fee: exactly 5 bps one-way
- New candidates/OOS: 0 / none

## Published versus corrected next-open results

| Market | Policy | Published return | Corrected return | Published Sharpe | Corrected Sharpe | Published edge/turnover | Corrected edge/turnover |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC | F0 | -1.2647% | -1.2604% | -0.1986 | -0.1978 | -2.3039 bps | -2.2930 bps |
| BTC | F1 | -0.5658% | -0.5678% | -1.0118 | -1.0164 | -10.0765 bps | -10.1122 bps |
| ETH | F0 | -1.1050% | -1.1108% | -0.0606 | -0.0617 | -0.8793 bps | -0.8954 bps |
| ETH | F1 | +2.3368% | +2.3145% | +1.7133 | +1.6997 | +22.0256 bps | +21.8217 bps |

Turnover and fee burden are unchanged because the target path is unchanged.

## Deterministic screens after repair

BTC F1 remains negative on return, Sharpe and edge per turnover, and remains worse than F0 on Sharpe and edge. It has only 1/5 profitable folds and 100% positive-fold concentration.

ETH F1 remains positive but has only 2/5 profitable folds, and its largest positive fold contributes 56.17% of positive-fold return. It cannot override BTC failure under the identical rule.

## Adjusted uncertainty

5,000 paired non-circular 168H block resamples within each fixed fold, preserving the fold boundary row once, seed 20260728:

- Worst-market F1−F0 Sharpe: -0.81857; one-sided 95% lower bound -3.60739; Holm p = 1.0.
- Worst-market F1−F0 edge/turnover: -7.81914 bps; lower bound -36.42893 bps; Holm p = 1.0.

A robustness rerun using common calendar block indices across BTC and ETH also rejects:

- Sharpe lower bound -2.90996; Holm p = 1.0.
- Edge lower bound -26.34380 bps; Holm p = 1.0.

DSR and PBO remain unreported because the deduplicated global architecture count and a valid CSCV selection matrix are unavailable.

## Artifact identity defect

- Artifact ID: `8689312077`
- ZIP SHA-256: `28e25dc4b6537b15f91b593306de630c4e948ff9cd1d993c423aa7a9be280331`
- Artifact `generated_from_commit`: `d7aa41480749f6cc9aa0357f6676863868b5b55f`
- Final PR #568 head: `27be6474201a8dd1915559996a86eb5bf291537c`
- The artifact contains no `execution_semantics` field.
- Its point estimates match the close-to-close core with zero error.
- The next-open wrapper was added after the artifact's claimed commit.

The strategy rejection remains valid, but the published execution-semantics claim is not valid evidence and is superseded by this reconstruction.
