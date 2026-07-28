# Source-Artifact Replication — Target-Innovation Hysteresis v1

## Verdict

`passed_same_base_artifact_replication_but_failed_candidate_neutral_transfer`

The unchanged H1 target-innovation hysteresis rule was independently reconstructed from two
immutable canonical workflow builds. The builds used different code heads, acquisition times,
artifact hashes, normalized snapshot hashes, and future source suffix lengths, while preserving the
same frozen BTC/ETH development window.

H1 produced identical discrete suppression decisions and economically identical performance in
both S0 builds. This proves same-path reproducibility, but a concurrent frozen transfer attack
shows that H1 is not candidate-neutral and must not be integrated as a general turnover overlay.

## Frozen policy

Policy SHA-256:

`437868cc0b2a166cf9b9a3f7dd28848a25664b567a9a6857c333108a3eb7fcf1`

- 168 prior completed canonical target innovations;
- `sigma = 1.4826 × MAD`;
- `band = 1.645 × sigma`;
- commit only when `abs(target - committed) > band`;
- equality is no-trade;
- state carries across folds;
- one-bar execution delay;
- exactly 5 bps one-way on absolute turnover.

No policy parameter or base strategy parameter was changed.

## Independent artifact builds

| Build | Workflow | Code head | BTC artifact | ETH artifact |
|---|---:|---|---:|---:|
| A | 30094766694 | `8387124b64d3ca4b9f196258a6928cc8d653e2ad` | 8597209253 | 8597205417 |
| B | 30347175588 | `d7cc15839755484b682d6e9094298b8a32f70230` | 8683465243 | 8683462187 |

All four published ZIP digests matched. Every artifact's 13 manifest-bound files reconstructed
successfully.

Build A contained 43,836 confirmed 1H snapshot rows through 2026-07-24 11:00 UTC. Build B contained
43,929 rows through 2026-07-28 08:00 UTC. The first 43,836 rows were byte-equivalent after CSV
parsing for both markets; Build B added 93 strictly future suffix rows.

The evaluated sample remained:

```text
markets                  BTC-USDT, ETH-USDT
evaluation               2023-07-24 00:00 UTC to 2026-07-07 23:00 UTC
observations per market  25,920
folds per market         12
fee                      exactly 5 bps one-way
new markets              0
new untouched OOS        false
```

## Reconstruction repair

A raw-hash-only comparison would have incorrectly treated the BTC returns CSVs as materially
different:

```text
Build A BTC returns SHA-256
986956a9df9b358488e6c8e847630fe532996a0438c3b112e2d602a4c6ac3958

Build B BTC returns SHA-256
72b34a405914057a71d6d47fa60251a591060d9d5220c717fbcf179b7073f1a6
```

The source prefix and selected fold configurations were identical. Downstream BTC target and
position values differed by at most `5.01e-16`, hourly H0 returns by at most `1.01e-16`, and hourly
H1 returns by at most `8.79e-18`. No H1 suppression decision changed. ETH returns were
byte-identical.

The replication therefore uses a two-tier fail-closed rule:

1. exact immutable artifact, manifest, source-prefix, timestamp, and selected-candidate identity;
2. downstream numeric tolerance of `1e-12`, with zero permitted discrete H1 decision changes.

## Strategy metrics

The two builds produced the same metrics to displayed precision.

| Market | Policy | Net return | Sharpe | Max drawdown | Annual turnover | Edge/turnover | Profitable folds |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC | H0 | 43.5898% | 0.6369 | -26.8428% | 45.2257 | 33.18 bps | 4/12 |
| BTC | H1 | 46.3675% | 0.6644 | -26.8256% | 30.6466 | 51.07 bps | 4/12 |
| ETH | H0 | 16.3126% | 0.3425 | -29.0291% | 62.3810 | 12.05 bps | 5/12 |
| ETH | H1 | 21.1196% | 0.4048 | -28.2962% | 45.6966 | 19.44 bps | 5/12 |

Equal-weight inference-only summary:

```text
net return      30.8887% -> 34.8541%
Sharpe           0.54165 -> 0.59019
annual turnover 53.8033  -> 38.1716
```

H1 improved fold return in 10 of 11 nonzero BTC fold comparisons and 10 of 12 ETH folds. It
improved total return and Sharpe in every calendar segment from 2023 through 2026. The H1-minus-H0
annualized arithmetic mean was positive in all four diagnostic causal trailing-168H volatility
quartiles for both markets.

## Uncertainty

For each build and market:

```text
5,000 paired resamples
168H non-circular blocks within folds
first row of each fold retained exactly once
seed 20260728
```

| Market | Endpoint | Observed H1-H0 | Basic 95% interval | One-sided 95% lower bound |
|---|---|---:|---:|---:|
| BTC | Annualized mean | +0.6466 pp | [+0.3279, +0.8100] pp | +0.3721 pp |
| BTC | Sharpe | +0.02756 | [+0.01330, +0.03464] | +0.01544 |
| ETH | Annualized mean | +1.3702 pp | [+0.9197, +1.7722] pp | +0.9919 pp |
| ETH | Sharpe | +0.06231 | [+0.04089, +0.08143] | +0.04430 |

Edge-per-turnover improvement remains statistically unconfirmed: the one-sided lower bound is
`-9.79 bps` for BTC and `-8.72 bps` for ETH.

A numerical Deflated Sharpe is not reported because the repository-wide independent family count
remains incomplete. PBO is not mathematically meaningful for two artifact builds of one unchanged
policy on the same market-time observations.

## Candidate-neutral transfer falsification

The unchanged H1 policy was also applied to the canonical 2,160H simple-trend long/cash path under
the same one-bar delay and 5 bps fee.

For both BTC and ETH:

```text
eligible decisions             25,751
zero-MAD decisions             25,751
positive-band decisions             0
suppressed nonzero revisions        0
H1-minus-H0 return                  0
H1-minus-H0 Sharpe                  0
H1-minus-H0 turnover                0
```

Sparse binary simple-trend target innovations make the rolling MAD exactly zero. H1 therefore
collapses to an identity transform rather than suppressing revisions. This falsifies the prior
candidate-neutral interpretation: H1's development benefit is structurally specific to the noisy
continuous S0 target path.

The combined verdict is:

```text
same-base artifact replication  PASS
candidate-neutral portability   FAIL
integration                     REJECT
archive status                  base-specific development diagnostic
```

H1 must not be retuned on the consumed BTC/ETH window or carried into a future selector by default.
Any new turnover overlay must be predeclared against the nominated target process using only
training-authorized information.

## Qualification boundary

The artifact-build replication proves only that H1 is reproducible on the same continuous S0 target
path. The portability attack rejects H1 for integration:

- BTC still has only 4/12 profitable S0 folds;
- ETH still has only 5/12 profitable S0 folds;
- H1 residual Sharpe versus simple trend remains negative on S0;
- H1 has exactly zero effect when transferred to the simple-trend target process;
- no untouched market or prospective period was used.

The next strategy-facing step is to repair and independently validate the frozen selector-comparison
evidence. H1 must remain archived and must not be automatically attached to any future nominated
policy.
