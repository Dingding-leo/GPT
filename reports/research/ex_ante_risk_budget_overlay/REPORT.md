# Fold-Local Ex Ante Strategy-Volatility Budget Overlay

## Hypothesis

At least one fixed fold-local ex ante strategy-volatility budget from the disclosed
15%, 20%, and 25% annualized family passes every BTC-USDT/ETH-USDT development-stage
architecture-freeze gate.

The economic rationale is direct: the canonical selector has historically concentrated
profits in relatively few folds and fails execution-delay robustness. This architecture
keeps the canonical 27-candidate signal selection unchanged, but adds a no-leverage
second-stage exposure budget. For each fold, the selected candidate's gross strategy
volatility is estimated only on the preceding 730 sessions. The next 90-session OOS fold
uses a fixed scalar:

```text
min(1, annualized risk budget / prior-window gross strategy volatility)
```

The overlay can only reduce exposure; it cannot lever a weak signal. SOL-USDT was not
accessed or used.

## Candidate accounting

Exactly one falsifiable family hypothesis and three fully disclosed architecture candidates
were tested:

```text
searched: 3
passed:   0
rejected: 3
```

No risk budget, threshold, fee, delay, benchmark, bootstrap setting, or market subset was
selected after viewing the results.

## Fixed method

- Provider: OKX public spot data.
- Development markets: BTC-USDT and ETH-USDT only.
- Timeframe: `1Dutc`.
- Evaluation: 2,385 strict OOS observations per market, 2020-01-11 through 2026-07-22 UTC.
- Base selection: canonical market-specific 27-candidate grid, 730-session selection and
  non-overlapping 90-session OOS folds.
- Risk budgets: 15%, 20%, and 25% annualized gross strategy volatility.
- Scale estimation: selected candidate's preceding 730-session gross strategy returns.
- Scale application: fixed through the following OOS fold, capped at 1.0.
- Baseline fee: 5 bps one-way per unit absolute position turnover.
- Fixed-path aggregate sensitivities: 7.5, 10, and 15 bps.
- Execution-delay stresses: total delays of two and three daily bars at every cost.
- Benchmark: persisted volatility-targeted-long return on identical timestamps.
- Inference: paired non-circular 20-session moving-block bootstrap, 2,000 resamples,
  95% confidence.

The 7.5/10/15 bps scenarios are aggregate repricings. Spread, slippage, market impact,
latency, partial fills, and capacity are not separately measured.

## Canonical 5 bps reference

| Market | Net return | CAGR | Sharpe | Sortino | Calmar | Max drawdown | Annual turnover |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | +142.091668% | 14.489118% | 0.706720 | 1.086817 | 0.510060 | -28.406668% | 16.425319 |
| ETH-USDT | +110.570789% | 12.070883% | 0.579467 | 0.851835 | 0.413662 | -29.180568% | 17.301475 |

## Exact candidate results at 5 bps

### 15% annualized risk budget

| Market | Net return | CAGR | Sharpe | Sortino | Calmar | Max drawdown | Annual turnover | Profitable folds |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | +103.538743% | 11.489842% | 0.773257 | 1.217202 | 0.604669 | -19.001864% | 10.500097 | 13/27 |
| ETH-USDT | +49.800418% | 6.380122% | 0.446251 | 0.637305 | 0.285591 | -22.340035% | 11.969021 | 17/27 |

### 20% annualized risk budget

| Market | Net return | CAGR | Sharpe | Sortino | Calmar | Max drawdown | Annual turnover | Profitable folds |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | +133.394054% | 13.849833% | 0.758226 | 1.184124 | 0.560286 | -24.719243% | 13.507469 | 12/27 |
| ETH-USDT | +77.720102% | 9.199246% | 0.523679 | 0.767409 | 0.357686 | -25.718767% | 14.865112 | 17/27 |

### 25% annualized risk budget

| Market | Net return | CAGR | Sharpe | Sortino | Calmar | Max drawdown | Annual turnover | Profitable folds |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | +142.938044% | 14.550284% | 0.724754 | 1.119025 | 0.513396 | -28.341267% | 15.698746 | 12/27 |
| ETH-USDT | +98.610393% | 11.072404% | 0.564452 | 0.831389 | 0.379444 | -29.180568% | 16.477178 | 17/27 |

The 15% overlay reduced BTC maximum drawdown, turnover, exposure, and positive-fold
concentration, but it still produced only 13 profitable folds versus the required 14. It
also materially weakened ETH benchmark-relative performance.

## Benchmark-relative inference

| Budget | Market | Sharpe delta, 95% interval | Calmar delta, 95% interval |
|---:|---|---:|---:|
| 15% | BTC-USDT | +0.030864, [-0.650246, +0.669376] | +0.223729, [-0.874771, +0.935459] |
| 15% | ETH-USDT | -0.480147, [-1.118589, +0.206529] | -0.355330, [-1.820550, +0.277880] |
| 20% | BTC-USDT | +0.015832, [-0.603000, +0.651800] | +0.179345, [-0.795113, +0.859290] |
| 20% | ETH-USDT | -0.402719, [-1.044834, +0.225168] | -0.283235, [-1.891855, +0.331299] |
| 25% | BTC-USDT | -0.017639, [-0.635497, +0.639655] | +0.132456, [-0.920675, +0.859810] |
| 25% | ETH-USDT | -0.361946, [-1.013880, +0.280863] | -0.261477, [-1.698603, +0.388402] |

Every required confidence lower bound is negative. No candidate establishes superior
risk-adjusted performance over volatility-targeted long in both development markets.

## Fold, year, cost, neighbourhood, tail, and delay gates

All three candidates:

- pass the complete-year rule in both markets;
- remain profitable with positive Sharpe and drawdown above -40% under fixed-path
  5/7.5/10/15 bps repricing;
- pass the disclosed adjacent-risk-budget neighbourhood check;
- have less severe daily 5% expected shortfall than volatility-targeted long;
- fail joint benchmark-relative risk-adjusted inference;
- fail joint fold stability because BTC has fewer than 14 profitable folds;
- fail execution-delay robustness.

At 15 bps, the 15% candidate still returned +90.046158% in BTC and +38.540434% in ETH.
This does not cure the statistical and stability failures.

No two-/three-bar delay candidate passed all eight cost-delay scenarios in both markets.
The worst 95% lower bounds for annualized mean and Sharpe remained negative.

## Verdict: rejected

No disclosed risk-budget candidate passes every required development architecture-freeze
gate. The family is therefore not eligible for architecture freeze, another untouched-market
test, prospective paper validation, or live deployment.

This result also rejects a narrower interpretation: simple fold-local exposure reduction
can lower BTC drawdown and concentration, but it does not create reliable cross-market
benchmark-relative performance or execution-delay robustness.

## Provenance

- Source workflow: `30040842607`.
- Source artifact: `8577163034`, `quant-research-source-348-attempt-1`.
- Artifact SHA-256:
  `a06f20584f243c4db1420e8ed0b6cacdc13eb11aebddefb72c30cc80176ccd45`.
- Source head: `eea39bc685246209cdb6c0d917fddcc6ef29f34b`.
- BTC snapshot SHA-256:
  `407aeba3d1ad4c8e8682a6a689c1c6327139f42bc7587aaae75c77fce047dec1`.
- BTC return SHA-256:
  `04a0a5257d1e20f1eb88c70b8a0b010d21f0dc35ccb657ba39f14189e9f20790`.
- ETH snapshot SHA-256:
  `842b4bbbb0ad7afbe2a1c9ee375443671d818a799266d5dc25cc6a548571ad7f`.
- ETH return SHA-256:
  `4b69db4a44644a5f830e1518aca93356c0eeacf502dc00ba990bd992b9bd387f`.

## Reproduction

```bash
sha256sum /path/to/quant-research-source-348.zip
unzip -q /path/to/quant-research-source-348.zip -d /tmp/qr348

python reports/research/ex_ante_risk_budget_overlay/generate_result.py \
  --artifact-dir /tmp/qr348 \
  --output /tmp/recomputed-risk-budget.json

cmp -s \
  /tmp/recomputed-risk-budget.json \
  reports/research/ex_ante_risk_budget_overlay/result.json

python -m py_compile \
  reports/research/ex_ante_risk_budget_overlay/analysis.py \
  tests/test_ex_ante_risk_budget_overlay_report.py

pytest -q tests/test_ex_ante_risk_budget_overlay_report.py
python -m json.tool reports/research/ex_ante_risk_budget_overlay/result.json
```

## Limitations

BTC-USDT and ETH-USDT remain development markets. SOL-USDT is a consumed sealed holdout
and was not accessed. The three risk budgets constitute a disclosed candidate family and
none passed. Volatility estimates use historical close-to-close gross strategy returns,
not executable fills. Delay stresses shift daily positions rather than model next-open
execution. Component-level friction, capacity, rejected orders, partial fills, and
prospective evidence remain unavailable.
