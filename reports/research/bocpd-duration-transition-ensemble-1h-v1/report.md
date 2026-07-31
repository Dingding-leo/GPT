# BOCPD duration-conditioned transition ensemble rejected

```text
family             bocpd-duration-transition-ensemble-1h-v1
classification     one-candidate executable temporal-ensemble experiment
candidate count    1
parameter grid     0
markets            BNBUSDT and VETUSDT independently
bar                immutable public Binance SPOT 1H
fee                exactly 5 bps one way
experiment head    6a1549aef7dd733c1476bfcb2b7b48ed718cdd36
markets accepted   0/2
verdict             reject_bocpd_duration_transition_ensemble_architecture_v1
```

## Strategy change

The experiment replaced direct BOCPD mean-state hysteresis with a fixed duration-conditioned transition ensemble. The complete causal run-length posterior was partitioned into four positive-mean duration experts—1–24H, 25–168H, 169–720H and 721–2,160H—plus a residual non-positive/uncertain expert. Each expert used a Beta(1,1) prior and training-only fractional updates to predict whether the next 24H same-instrument open-to-open return would exceed the exact 10 bps round-trip fee. Expert counts were frozen at OOS start. The daily 00:00 UTC target was long only when the mixture probability was strictly above 0.50; otherwise cash.

No threshold, duration bin, prior, horizon, BOCPD parameter, market-specific rule or OOS update was searched.

## Immutable data and sample

| Field | Frozen specification |
|---|---|
| Provider | Anonymous Binance public monthly archives |
| Markets | BNBUSDT and VETUSDT, evaluated independently |
| Source | 1 April 2023–31 December 2025 UTC |
| Rows | 24,144 contiguous 1H bars per market |
| Warm-up | `[0,2,160)` |
| Training | `[2,160,10,800)`; four 2,160H blocks |
| OOS | `[10,800,23,760)`; six 2,160H folds |
| Full scored | `[2,160,23,760)` |
| Unscored suffix | `[23,760,24,144)` |
| Uncertainty | 5,000 paired non-circular 168H moving blocks; seed `20260801` |

Canonical source SHA-256 values were `fea225b0dbce90933933f3b3fc172306f6d40a5e045bc00c07fa378dc511d7fb` for BNBUSDT and `cdea30ad9ca9f97e293d1f5cd9b13b7e575ed5c53952288c3658a8e60e477e69` for VETUSDT. Every monthly archive matched its companion checksum and the concatenated grids were strictly hourly and continuous.

## Exact performance

| Market | Segment | Candidate net | Sharpe | Max DD | Trend net | Parent net | Turnover |
|---|---|---:|---:|---:|---:|---:|---:|
| BNBUSDT | train | +49.6197% | +1.0673 | −31.4628% | +128.2014% | +66.9488% | 62 |
| BNBUSDT | OOS | +41.9122% | +0.7056 | −35.7507% | +12.0388% | −41.1160% | 52 |
| BNBUSDT | full | +112.5411% | +0.8418 | −42.1563% | +155.6746% | −1.6939% | 112 |
| VETUSDT | train | +2.7917% | +0.3931 | −34.7385% | +74.1662% | −5.7859% | 76 |
| VETUSDT | OOS | −28.7145% | −0.5196 | −52.2613% | +17.6613% | −26.7053% | 72 |
| VETUSDT | full | −26.7244% | +0.0139 | −53.6203% | +104.9262% | −30.9460% | 148 |

BNB OOS exposure was 91.30%, fee drag 2.60%, and edge per turnover +0.8060%. VET OOS exposure was 13.15%, fee drag 3.60%, and edge per turnover −0.3988%. BNB's median OOS long episode was 204H; VET's was only 24H.

## Breadth, uncertainty and calibration

BNB produced positive OOS fold returns in 4/6 folds and positive calendar returns in both 2024 and 2025. Its candidate-minus-trend mean hourly net-return difference was +0.2276 bps, but the 95% moving-block interval was `[−0.3147,+0.8028]` bps. Candidate-minus-parent was +0.7827 bps with interval `[−0.0075,+1.6180]` bps. BNB passed 11/12 gates; only the required positive uncertainty lower bounds failed.

VET produced positive OOS fold returns in 2/6 folds and positive calendar return in 1/2 years. Candidate-minus-trend was −0.5898 bps with interval `[−1.7664,+0.4940]` bps; candidate-minus-parent was −0.1352 bps with interval `[−1.2318,+0.8254]` bps. VET passed only 3/12 gates.

OOS probability calibration improved marginally versus the frozen unconditional training base rate in both markets:

```text
BNB log loss  0.692436 vs 0.693466; Brier 0.249644 vs 0.250159
VET log loss  0.691231 vs 0.692096; Brier 0.249045 vs 0.249475
```

The one-extra-hour delay stress remained positive for BNB at +48.8545% but remained negative for VET at −8.0323%.

## Failure mechanism

The transition ensemble learned slightly better fee-clearing probabilities, but calibration did not transport into bilateral economic edge. BNB was economically strong yet statistically unresolved and still underperformed buy-and-hold. VET reversed from a marginally positive training result to −28.7145% OOS, with the average duration-weight distribution shifting by L1 distance 0.1472 versus 0.0761 for BNB. Its frozen expert probabilities and changed duration mixture kept most OOS decisions below 0.50, producing low exposure and short long episodes without avoiding losses.

The complete run-length posterior therefore did not supply replicated information about future fee-clearing trend persistence. Same-cohort changes to bins, priors, threshold, label horizon, BOCPD parameters, online OOS updating or market deletion are closed.

## Correctness repairs

The initial frozen source interval failed before performance because the checksum-valid March 2023 BNB archive omitted one hourly row. The source start was moved to April 2023 before any strategy metric or OOS value was observed, with every strategy-facing value unchanged. A second non-strategy repair replaced a damaged compressed-payload transfer with deterministic five-part assembly and post-decompression SHA-256 verification. Neither repair changed market data inside the final contract, signals, positions, labels, fees, metrics, gates or verdict.

## Disposition

```text
Architecture accepted      No
Architecture rejected      Yes
Canonical strategy changed No
Evidence merge authorised  No
Paper/live authority       None
```

**Remaining blocker:** a causal temporal model must forecast the magnitude and persistence of net long opportunity across instruments, not merely improve calibration of a binary 24H fee-clearing event.

**Next experiment:** preregister one fixed multi-horizon state-space trend ensemble on a fresh immutable cohort. Use causal local-linear-trend filters at predetermined 24H, 168H and 720H process scales; combine their posterior slope distributions with frozen training-only proper-score weights; and apply one turnover-cost-aware hysteretic long/cash rule. Authorise no canonical change unless both instruments pass OOS net return, benchmark superiority, drawdown, edge-per-turnover, fold/year breadth, moving-block lower-bound and delay gates.
