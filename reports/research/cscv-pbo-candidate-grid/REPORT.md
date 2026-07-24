# CSCV Probability of Backtest Overfitting for the Declared Candidate Grid

## Hypothesis

The declared 27-configuration BTC-USDT and ETH-USDT candidate grids each have a
Probability of Backtest Overfitting (PBO) no greater than 5% under 12-subsample
Combinatorially Symmetric Cross-Validation (CSCV), using the repository's exact
candidate-selection score.

Economic rationale: the rolling process searches 27 momentum/reversal/weight combinations.
A positive selected path is not persuasive if configurations that rank well in one half of
history usually rank in the bottom half of the complementary history.

## Predeclared method

- Markets: OKX spot BTC-USDT and ETH-USDT `1Dutc`, development evidence only.
- Evaluation interval: 2,340 observations from 2020-01-11 through 2026-06-07 UTC.
- Candidate grid: momentum `{30, 90, 180}` × reversal `{2, 5, 10}` × trend weight
  `{0.55, 0.70, 0.85}` = 27 fixed paths per market.
- Every candidate uses the existing one-bar execution delay, long/cash constraint,
  50% volatility target, and 10 bps per unit turnover.
- The script reconstructs the persisted adaptive selected path before analysis; maximum
  absolute return error is below `1e-15` for both markets.
- The 2,340 observations are split into 12 contiguous 195-observation subsamples.
- All `choose(12, 6) = 924` in-sample/complement pairs are evaluated.
- Candidate ranking uses the repository score:

  `Sharpe + 0.20 × Calmar - 0.50 × |max drawdown| - 0.01 × annualized turnover`.

- For the in-sample winner, the complementary-sample ascending rank is converted to
  `omega = rank / (27 + 1)` and `lambda = log(omega / (1 - omega))`.
- A split is classified as overfit when `lambda <= 0`, meaning the in-sample winner ranks
  in the bottom half out of sample.
- The joint hypothesis passes only if PBO is at most 5% in both markets.

No alternative block count, rank convention, score, threshold, candidate subset, market
subset, cost, or execution delay was selected after observing the result.

## Results

| Market | Overfit splits | CSCV splits | PBO | Median OOS rank | Median logit | Verdict |
|---|---:|---:|---:|---:|---:|---|
| BTC-USDT | 410 | 924 | 44.3723% | 16 / 27 | 0.287682 | Reject |
| ETH-USDT | 316 | 924 | 34.1991% | 20 / 27 | 0.916291 | Reject |

Both PBO estimates substantially exceed the predeclared 5% limit. The candidate grid's
in-sample winner lands in the out-of-sample bottom half in 410 BTC splits and 316 ETH
splits. The joint hypothesis is therefore **rejected**.

This is not evidence that every configuration loses money, nor is it a new strategy search.
It is evidence that relative candidate rankings are unstable under this CSCV specification.
No stronger alpha or deployment claim is made.

## Candidate accounting

- Joint hypotheses searched: 1.
- Supported: 0.
- Rejected: 1.
- Fixed grid candidates evaluated per market: 27.
- CSCV splits evaluated per market: 924.
- All 27 candidate identities and their in-sample selection frequencies are persisted in
  `result.json`, including zero-frequency candidates.

Canonical signature:

`cscv-pbo-selection-score-v1|markets=BTC-USDT,ETH-USDT|source=immutable-OKX-1Dutc-snapshots|candidate-grid=3x3x3-27|candidate-path=fixed-parameter-one-bar-delayed-10bps-long-cash|evaluation=2020-01-11..2026-06-07-2340-bars|subsamples=12x195-contiguous|splits=choose(12,6)=924|is-selection=repository-score|oos-ranking=repository-score-average-tie-rank|omega=ascending-oos-rank/(27+1)|lambda=log(omega/(1-omega))|pbo=share(lambda<=0)|pass=pbo<=0.05-for-both-markets|candidate_count=1`

## Provenance

- Source workflow: `29913443745`.
- Source artifact: `8526866832`, `quant-research-source-917-attempt-1`.
- Artifact SHA-256:
  `ac6a8811a3d26fc38b954c7e779c0aacb0f0feafb78afaee712a8a2fd64908cb`.
- Source head: `1a37205e935f4d1d2544a96c11430b7d05f31295`.
- BTC snapshot SHA-256:
  `b0bd7c6c7e30fcc095073169f60bde24559f481b24cc6f4bdfb85349f57974bb`.
- ETH snapshot SHA-256:
  `78f3bf81d3983e6c894066a1c298fbf14ae06a5eff9ca7326554b0a8933c0df5`.
- Exact report and persisted-return hashes are recorded in `result.json`.

## Reproduction

```bash
python reports/research/cscv-pbo-candidate-grid/analysis.py \
  --artifact-dir /path/to/unpacked/quant-research-source-917 \
  --output /tmp/recomputed-pbo.json

cmp -s \
  /tmp/recomputed-pbo.json \
  reports/research/cscv-pbo-candidate-grid/result.json
```

## Limitations

BTC and ETH are development markets, not untouched holdouts. CSCV concatenates disjoint
observed blocks when calculating path-dependent metrics, which creates artificial joins;
it does not fabricate market observations or reprice omitted boundaries. The 12-block
choice is one fixed, mathematically compatible partition and was not varied. PBO covers the
27 declared parameter configurations, not the repository's larger history of strategy ideas.
Liquidity, spread, market impact, capacity, latency, and partial fills remain unmodeled.
