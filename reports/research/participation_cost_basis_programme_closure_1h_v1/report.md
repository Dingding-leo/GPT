# Own-price participation / transaction-cost-basis programme closure 1H v1

## Terminal verdict

```text
family                  causal-own-price-participation-cost-basis-programme-closure-1h-v1
canonical main          5a0fcc97d1a882f8223656c51f5bb8055f534e38
bound groups            3
historical candidates   8
new candidates/grid     0/0
new rows/labels/OOS     0/0/0
admissible groups       0/3
programme gates passed  3/10
fee                     exactly 5 bps one way wherever bound economics were authorised
canonical mutation      none
paper/live authority    false/false
verdict                 reject_reopening_completed_own_price_participation_cost_basis_mechanisms_1h_v1
```

The completed public own-price participation programme is rejected against further algebraic rescue. All three immutable architecture groups reconcile exactly, but none contains an independently admissible bilateral mechanism under its original source, economics, risk, turnover, breadth, dependence and execution-delay gates.

## Bound evidence matrix

| Group | Completed mechanisms | Historical candidates | Independently admissible | Decisive evidence |
|---|---:|---:|---:|---|
| Aggregate participation / activity-time (#909) | 3 | 0 | 0 | 3/3 source-valid and variable, but 0/3 bilateral-supportive; no OOS/economics authorised |
| Directional price-volume interaction (#1027) | 6 | 8 | 0 | isolated OOS point gains, but negative training, turnover/risk, breadth, dependence, source or delay failures |
| VWAP/TWAP transaction-cost-basis migration (#1088) | 1 | 0 | 0 | bilateral negative return association; no positive bootstrap lower bound; delay remains negative |

### Group A — aggregate participation

Exact closure head `3d729361b58c1352bf402462f736514b7151b107`, focused run `30716812657`, artifact `8823578439`, ZIP SHA-256 `3ecb3b74cf5117f69f40901f95a2a2f58d3c2888512dcbc9de3a13e0c8150708`, evidence SHA-256 `f4c3a49d0b94e7799f8b92fac469937a1f719abe39740989102c69793ca8fe9e`.

All three mechanisms used immutable public Binance SPOT 1H, 24,144 rows per market. Trade-count clock had only 38 APT and 25 LDO E2160 disagreements and inadequate quarter/concentration support. Price-adjusted average trade size generated 12 ATOM vetoes but zero NEAR vetoes. Range-impact generated 18 AVAX vetoes but zero FIL vetoes. Bilateral support was `0/3`, OOS-authorised groups `0/3`; strategy economics are null rather than zero.

### Group B — directional price-volume interaction

Exact closure head `270f9951b1bd16f06227da768aad74b375552e85`, focused run `30787837821`, artifact `8845886112`, ZIP SHA-256 `56180347933cf65ac63fc0bc7416f5b8ca1024cd8a156255cde396909b5b90f0`.

The strongest point estimate is the volume-weighted directional persistence entry:

| Market | Train return / Sharpe | OOS candidate | OOS E2160 | OOS DD cand/base | OOS turnover cand/base | OOS edge/turn cand/base |
|---|---:|---:|---:|---:|---:|---:|
| BTC | -24.65% / -0.428 | +141.18% / 1.071 | +119.68% / 0.954 | -30.94% / -26.55% | 23 / 45 | 451.96 / 212.75 bp |
| ETH | -24.11% / -0.287 | +140.70% / 0.899 | +74.52% / 0.646 | -44.90% / -47.77% | 10 / 30 | 1159.89 / 283.58 bp |

This supplies the programme's only bilateral point-estimate return/Sharpe benchmark pass, but it is not admissible: both training sleeves lose money, each market has only `6/12` profitable folds, BTC drawdown worsens, and dependence lower bounds are non-positive (`BTC mean delta -0.0787, Sharpe delta -0.1997`; `ETH mean delta -0.0193, Sharpe delta -0.028`).

Other bound mechanisms fail by negative economics/extreme turnover (#543), benchmark timing and breadth (#645), one-market de-risking/turnover and dependence (#685), exact source coverage (#566), or bilateral negative lead-lag information with failed delay/dependence (#1025).

### Group C — transaction-cost-basis migration

Exact execution head `f641f725cd90fe812e6d3f0ea8d63e1d3d2957a6`, focused run `31240124268`, artifact `9016796257`, ZIP SHA-256 `47b8aa42c5b12b29cbf43d3512f5ee5d85fdfc87209f70c36265ef76736966fa`.

Public OKX SPOT native completed 1H, 2023-04-01 through 2025-12-31 UTC, 24,144 rows per target; training `[2208,10800)`, sealed OOS `[10800,23760)` remained unread.

| Target | Opps | Net rho / slope | Net tercile | Adverse rho / slope | Adverse tercile | + folds net/adverse |
|---|---:|---:|---:|---:|---:|---:|
| 1INCH | 174 | -0.024829 / -0.003833 | -41.10 bp | -0.025836 / -0.004363 | -86.33 bp | 2/4 / 0/4 |
| SNX | 194 | -0.034144 / -0.001114 | -105.28 bp | +0.018829 / -0.000189 | -1.62 bp | 2/4 / 2/4 |

No required 5,000-draw moving-block lower bound was positive. Delayed net slope/tercile remained negative in both markets (`1INCH -0.003653 / -60.13 bp`; `SNX -0.000615 / -92.09 bp`). No candidate or OOS strategy metric was authorised.

## Programme gates

| # | Gate | Result |
|---:|---|---|
| 1 | all bound group identities and terminal verdicts reconcile | PASS |
| 2 | at least one group contains independently admissible bilateral mechanism | FAIL |
| 3 | positive train oos full economics exists where required | FAIL |
| 4 | bilateral point estimate return and sharpe superiority vs frozen benchmark exists | PASS |
| 5 | joint drawdown turnover and edge per turnover improvement exists bilaterally | FAIL |
| 6 | original fold year breadth and concentration passes bilaterally | FAIL |
| 7 | strictly positive bilateral dependence aware lower bounds exist | FAIL |
| 8 | every applicable one hour execution delay gate supportive bilaterally | FAIL |
| 9 | no supportive claim requires posthoc target period sign or normalization change | PASS |
| 10 | each leave one group out subset retains admissible support | FAIL |

Only gates 1, 4 and 9 pass. Every leave-one-group-out subset retains **zero** independently admissible mechanisms.

## Closure performance accounting

This run created no target path or equity curve. Therefore its own train/OOS/full return and Sharpe, benchmark return/Sharpe, turnover, fee drag, maximum drawdown, edge per turnover, fold/year breadth, uncertainty and one-hour-delay strategy metrics are **null rather than zero**. No market row, target label, benchmark value, bootstrap draw or OOS observation was newly acquired or recomputed.

## Strategy conclusion

Participation information has repeatedly been active without being transportably useful. The strongest mechanism can improve one OOS regime and lower turnover, yet fails training, breadth, dependence and BTC risk. Aggregate activity representations often do not alter decisions bilaterally at all. Transaction-price migration then produces the wrong return sign in two fixed external targets. Continuing with another OHLCV/aggregate-volume/trade-count algebra would spend multiplicity on a consumed information channel rather than improve expected net performance.

Closed rescue scope: alternate base/quote-volume ratios; VWAP/TWAP definitions; volume/trade-count clocks; average-trade-size and range-per-participation transforms; effort/result ratios; signed-volume weighting; lead/lag orientation; volume slopes; recent/baseline windows; clipping, winsorisation or smoothing; thresholds; market-specific settings; E2160 overlays; fractional sizing; feature ensembles; target substitution or post-hoc filtering on consumed cohorts.

## Deterministic evidence identity

`evidence.json` SHA-256: `d78caaba25b3fc36073045a8c66581c1181f2444bed7063772cd6c5d41cb6158`.

No next architecture is encoded in this artifact; it must be nominated only after terminal disposition of this closure.
