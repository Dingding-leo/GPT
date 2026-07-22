# Deflated Sharpe Multiple-Testing Diagnostic

## Hypothesis

BTC-USDT and ETH-USDT aggregate net rolling out-of-sample Sharpe ratios exceed the
expected maximum under 27 independent zero-skill trials with at least 95% probability
after sample skewness and kurtosis are included.

Economic rationale: the rolling selector searches 27 parameter configurations in every
selection window. A positive raw Sharpe is not persuasive if it does not clear the return
non-normality and selection benchmark implied by that candidate family.

Canonical signature:

```text
deflated-sharpe-independent-null-v1|markets=BTC-USDT,ETH-USDT|source=persisted-net-rolling-oos-returns|observed-sharpe=mean/std-ddof0|annualization=365|selection-adjustment=expected-maximum-of-independent-zero-skill-normal-trials|effective-trials=27|trial-standard-error=1/sqrt(n-1)|non-normality=fisher-pearson-skew-and-raw-kurtosis|pass=dsr-probability-at-least-0.95-for-both-markets|candidate_count=1
```

Exactly one joint candidate was tested. No alternate trial count, Sharpe convention,
non-normality estimator, probability threshold, market subset, fee, execution delay, or
acceptance rule was selected after observing the result.

## Method

For each market, the analysis uses all 2,340 persisted net rolling OOS returns and the
repository's daily Sharpe convention:

```text
SR_daily = mean(return) / std(return, ddof=0)
```

The expected maximum of 27 independent standard-normal null trials is approximated by
the Bailey–López de Prado extreme-value expression:

```text
z_max = (1 - gamma) * Phi^-1(1 - 1/N)
        + gamma * Phi^-1(1 - 1/(N * e))
SR_benchmark = z_max / sqrt(n - 1)
```

The Deflated Sharpe probability is the Probabilistic Sharpe Ratio evaluated against that
selection benchmark:

```text
z_DSR = (SR_daily - SR_benchmark) * sqrt(n - 1)
        / sqrt(1 - skew * SR_daily + ((kurtosis - 1) / 4) * SR_daily^2)
DSR = Phi(z_DSR)
```

`kurtosis` is raw kurtosis: unbiased Fisher excess kurtosis plus three. The joint
hypothesis passes only when both market probabilities are at least 95%.

Reference: Bailey and López de Prado, *The Deflated Sharpe Ratio: Correcting for
Selection Bias, Backtest Overfitting, and Non-Normality*, Journal of Portfolio
Management 40(5), 2014, DOI `10.3905/jpm.2014.40.5.094`.

## Results

| Market | Observed annualized Sharpe | Deflated benchmark | Skewness | Raw kurtosis | PSR vs zero | DSR probability | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| BTC-USDT | 0.725970 | 0.801755 | 0.592300 | 19.320127 | 96.80% | 42.33% | Reject |
| ETH-USDT | 0.537986 | 0.801755 | 0.384948 | 19.558644 | 91.42% | 25.14% | Reject |

BTC's unadjusted probabilistic Sharpe probability versus zero is above 95%, but its DSR
falls to 42.33% after the 27-trial benchmark and non-normality adjustment. ETH fails both
the 95% unadjusted probability threshold and the DSR threshold.

## Verdict

**Rejected.** One candidate was searched, zero passed, and one was rejected. Neither
market's annualized Sharpe exceeds the 0.801755 multiple-testing benchmark, and both DSR
probabilities are far below 95%. No alpha, Sharpe significance, or deployable improvement
is claimed.

## Real-data provenance

- Provider: OKX spot.
- Timeframe: `1Dutc`.
- Markets: BTC-USDT and ETH-USDT.
- OOS period: 2020-01-11 through 2026-06-07 UTC.
- OOS observations: 2,340 per market.
- Transaction cost: 10 bps per unit turnover.
- Execution timing: one-bar delayed position.
- Selection/test lengths: 730/90 bars, non-overlapping test folds.
- Candidate grid: 27 configurations.
- Source workflow: `29912901356`.
- Source artifact: `8526644006`, `quant-research-source-904-attempt-1`.
- Source artifact SHA-256:
  `e547d220d6f1f1649038387471c3cf9fef6da6d9f71d793f80ee2b0d114bcca4`.
- Tested checkout: `5528e1677fab9dd6e8b1b60ae00f2205f4116ead`.
- Persistent source head: `205864d115a9043cb15a6215f8e3d058edb4dd69`.
- Tested base: `4f745926277fbf64ce06294e8c43322a1f9800e6`.

Per-market return and report hashes are persisted in `result.json`.

## Reproduction

```bash
sha256sum quant-research-source-904.zip
unzip -q quant-research-source-904.zip -d /tmp/quant-research-source-904

python reports/research/deflated-sharpe-multiple-testing/analysis.py \
  --artifact-dir /tmp/quant-research-source-904 \
  --output /tmp/recomputed-deflated-sharpe.json

cmp -s \
  /tmp/recomputed-deflated-sharpe.json \
  reports/research/deflated-sharpe-multiple-testing/result.json

python -m py_compile \
  reports/research/deflated-sharpe-multiple-testing/analysis.py \
  tests/test_deflated_sharpe_multiple_testing_report.py

pytest -q tests/test_deflated_sharpe_multiple_testing_report.py
```

## Limitations

- BTC-USDT and ETH-USDT are development markets, not untouched holdouts.
- The effective-trial count is the declared 27-configuration grid. It does not include
  prior experiment versions, discretionary research directions, or repeated fold-level
  selection as additional effective trials, so the adjustment is a lower bound on the
  full research-selection burden.
- The independent-null DSR benchmark does not model correlation among candidate Sharpe
  ratios because complete per-candidate trial Sharpe dispersion is not persisted.
- The analytic DSR formula does not preserve serial dependence in the way a moving-block
  bootstrap does; it is reported as a separate multiple-testing diagnostic.
- Spread, nonlinear market impact, liquidity, capacity, latency, and partial fills remain
  unmodeled.
