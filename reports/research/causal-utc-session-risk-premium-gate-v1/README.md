# Causal UTC session-risk-premium gate v1

## Verdict

`rejected_exact_family_cooldown`

This development-only feature experiment tested whether a recurring UTC weekday/session risk premium can improve the existing causal per-instrument 1H long/cash strategy. It used only each target market's own prior confirmed returns. It did not inspect untouched markets or new prospective OOS data.

## Frozen policy

For each execution bar, the relevant session was one of three fixed UTC blocks: 00:00–08:00, 08:00–16:00, or 16:00–24:00. Day-of-week × session produced 21 bins.

Before a block began, the experiment selected the most recent 104 complete historical blocks in the same bin, required at least 52, and computed:

```text
LCB = mean(block_return) - 1.645 * std(block_return, ddof=1) / sqrt(n)
gate = 1 if LCB > 0 else 0
```

The candidate execution position was the unchanged canonical intended position multiplied by this gate. Equality, unavailable history, malformed chronology, gaps, duplicates, or unconfirmed candles failed closed to cash. Turnover and exact 5 bps one-way fees were recomputed over the continuous OOS path.

Exactly one alternative was evaluated. No session boundary, history length, minimum count, confidence multiplier, position fraction, or rescue combination was searched.

## Immutable evidence

- Workflow run: `30347175588`
- Source head: `d7cc15839755484b682d6e9094298b8a32f70230`
- BTC artifact: `8683465243`
- BTC ZIP SHA-256: `e9bdc2cee531f0b71539a6f4c2b306f2ae702e64bbbe8443ec16bf69c558147a`
- ETH artifact: `8683462187`
- ETH ZIP SHA-256: `1f865024ae9d3ce7aa51bfe72bbab054b0377eef01780c75f60f6e8aa2cdc51e`
- Confirmed snapshot rows: 43,929 per market
- OOS rows: 25,920 per market
- OOS interval: 2023-07-24 00:00 UTC through 2026-07-07 23:00 UTC
- Folds: 12 × 2,160 hours per market
- Candidate count: 1
- Policy-fold evaluations: 48

Both ZIP digests and all internal manifest entries were verified. Canonical turnover, gross return, fee, and net return were reconstructed within `1e-11`.

## Results

| Market | Policy | Net return | Sharpe | Max drawdown | Annual turnover | Edge/turnover | Profitable folds |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC-USDT | canonical | +43.59% | +0.637 | -26.84% | 45.23 | +33.18 bps | 4/12 |
| BTC-USDT | session gate | -12.82% | -0.744 | -17.73% | 55.80 | -7.99 bps | 3/12 |
| ETH-USDT | canonical | +16.31% | +0.342 | -29.03% | 62.38 | +12.05 bps | 5/12 |
| ETH-USDT | session gate | -10.63% | -0.825 | -14.24% | 23.72 | -15.59 bps | 2/12 |

Residual Sharpe versus the canonical simple-trend benchmark worsened:

```text
BTC  -0.8180 -> -1.0721
ETH  -0.5867 -> -0.7074
```

The gate was active for only 7.93% of BTC hours and 4.72% of ETH hours. It did reduce the worst 24-hour and 168-hour losses because it remained mostly in cash, but this was not a risk-adjusted improvement: net return, Sharpe, Calmar, edge per turnover, fold breadth, and benchmark residuals all failed.

## Feature calibration

The causal lower-confidence bound had essentially no relation to the next realized same-bin block return:

```text
BTC LCB/realized correlation   -0.0041
ETH LCB/realized correlation   +0.0081
```

Gate-on blocks were not positive out of sample:

```text
BTC gate-on mean block return   -0.0033%
BTC gate-off mean block return  +0.0352%

ETH gate-on mean block return   -0.1945%
ETH gate-off mean block return  +0.0259%
```

The feature therefore selected the wrong temporal states rather than merely suffering from fees.

## Realized-edge decomposition

```text
BTC gross annualized mean delta   -18.93 percentage points
BTC annualized fee delta           +0.53 percentage points
BTC net annualized mean delta     -19.46 percentage points

ETH gross annualized mean delta   -13.15 percentage points
ETH annualized fee delta           -1.93 percentage points
ETH net annualized mean delta     -11.21 percentage points
```

BTC also increased annualized turnover because binary session entries and exits exceeded the canonical micro-adjustments they suppressed. ETH reduced turnover, but the lost gross exposure dominated the fee savings.

## Uncertainty

The experiment used 5,000 paired, non-circular 168-hour moving-block resamples within folds. Each fold boundary row was preserved exactly once. The exact seed was `20260728` for both markets.

```text
BTC Sharpe delta                  -1.3813
one-sided 95% lower bound         -2.0599
BTC edge/turnover delta          -41.17 bps
one-sided 95% lower bound        -83.39 bps

ETH Sharpe delta                  -1.1676
one-sided 95% lower bound         -2.3969
ETH edge/turnover delta          -27.64 bps
one-sided 95% lower bound        -65.57 bps
```

All four Holm-adjusted confirmatory p-values were `1.0`. DSR and PBO were not calculated because the repository-wide independent-family count and complete candidate-by-split matrix remain unavailable.

## Causal validation and repair

Passed checks:

- future-suffix mutation left all earlier gates unchanged;
- current and future session blocks were excluded from estimation;
- duplicated, shuffled, gapped, and unconfirmed real-data copies were rejected;
- feature missingness was zero in the evaluated OOS interval;
- repeated canonical JSON serialization was byte-identical.

The first implementation used a different bootstrap seed offset for ETH. Before publication, this was repaired to the single frozen seed `20260728` for both markets, ensuring identical fold/block resampling coordinates across independent market replications. The full experiment was rerun; the verdict was unchanged.

## Cooldown

The exact family is closed on this BTC/ETH development window:

```text
3 × 8H UTC sessions
21 weekday/session bins
trailing 104 same-bin observations
minimum 52 observations
1.645 one-sided LCB
binary canonical-position gate
```

It may not be rescued on the same data by changing session boundaries, confidence level, history length, minimum observations, gate direction, fractional exposure, or combining it with the H1 hysteresis overlay.

## Reproduction

Run `reproduce.py` after placing the two immutable workflow artifact ZIPs at `/mnt/data/btc.zip` and `/mnt/data/eth.zip`. The script verifies the published ZIP and internal manifest hashes before calculating any metric.
