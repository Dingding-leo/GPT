# Sealed LTC-USDT validation

## Verdict

**Rejected.** The predeclared joint hypothesis required both the repository's unchanged robustness classifier to return a non-reject classification and the paired moving-block-bootstrap lower bound for maximum-drawdown improvement versus volatility-targeted long to be positive.

- Condition 1 — repository non-reject: **failed** (`reject: non-positive aggregate out-of-sample result`).
- Condition 2 — volatility-targeted-long max-drawdown delta lower bound > 0: **passed** (`0.216166`).
- Joint verdict: **rejected**. No same-market retuning was performed.

## Frozen protocol and provenance

- protocol commit before data access: `7b9a8128539c10cc302f80602efd9f3973850592`;
- frozen base commit: `29c28c1031bddda6c5e42f2672aaa6adaa004cad`;
- workflow run: `29859059348` (`quant-research-234`);
- workflow artifact: `8506548343` (`quant-research-234`);
- artifact SHA-256: `ad863c515d657b1445c20d50293c49a3539b490f47e641feabf7420763944a03`;
- tested merge SHA: `1e5b0715f5b73ce36ca75ad23bd8fc1e9c08a2ad`;
- provider/instrument/bar: `OKX` / `LTC-USDT` spot / `1Dutc`;
- normalized CSV SHA-256: `1f9f6ccb8d3ccd798b0ce47956d39f44ae17b50bc1f5c13edee3c890a364e97c`;
- raw response SHA-256: `f7a3c279523e34a84b4a2241ebd6c26d4f6840a9d174151ad1529b418100d85d`;
- walk-forward returns SHA-256: `701d51bc0bd7217402c3910ccb84c23a71e479864a29f03227e0c6391b4ab87d`;
- observations: 2392 confirmed daily bars from 2020-01-02 to 2026-07-20;
- missing intervals: 0; duplicates removed: 0; unconfirmed rows removed: 1.

Canonical signature:

`sealed-market-v2-v1|provider=OKX|market_type=spot|market=LTC-USDT|bar=1Dutc|start=2017-01-01|code=29c28c1031bddda6c5e42f2672aaa6adaa004cad|config_sha256=992ed2f5ea53cd3704cdfc876c1f464b0c618590aface911d781421f672398c5|selection_bars=730|test_bars=90|grid=3x3x3|transaction_cost_bps=10|execution_delay=1bar|benchmark=volatility-targeted-long|metric=max_drawdown_delta|block=20|resamples=2000|confidence=0.95|seed=20260722|accept=repository_nonreject_and_ci_lower_gt_0`

## Candidate accounting

The search space was frozen before data access:

- momentum lookbacks: `30`, `90`, `180`;
- reversal lookbacks: `2`, `5`, `10`;
- trend weights: `0.55`, `0.70`, `0.85`;
- 27 candidates per fold × 18 folds = **486 candidate evaluations**;
- 730-bar trailing selection windows and non-overlapping 90-bar OOS test windows;
- one-bar execution delay, long/cash only, 10 bps per unit turnover;
- cost stress at 1×, 2×, and 4×; unchanged parameter-neighbourhood perturbations.

All 27 candidates were evaluated in every fold. No candidate, threshold, market, fee, split, seed, or bootstrap setting was added or removed after viewing the LTC result.

## Fold results

| Fold | Test period | Selected (m/r/trend) | Selection score | OOS return | OOS Sharpe | OOS max DD |
|---:|---|---|---:|---:|---:|---:|
| 1 | 2022-01-01–2022-03-31 | 180/10/0.70 | 1.245261 | 1.2671% | 0.6446 | -3.6782% |
| 2 | 2022-04-01–2022-06-29 | 30/10/0.55 | 1.341528 | -7.5386% | -1.8819 | -11.3737% |
| 3 | 2022-06-30–2022-09-27 | 90/10/0.55 | 1.432448 | -1.6309% | -1.1024 | -3.6564% |
| 4 | 2022-09-28–2022-12-26 | 90/10/0.55 | 1.402187 | 2.7203% | 1.0114 | -6.3920% |
| 5 | 2022-12-27–2023-03-26 | 90/10/0.55 | 0.786261 | 6.8709% | 1.0844 | -15.6407% |
| 6 | 2023-03-27–2023-06-24 | 90/10/0.55 | 0.591012 | -2.6681% | -0.6296 | -8.9197% |
| 7 | 2023-06-25–2023-09-22 | 90/10/0.55 | 0.354714 | -5.4085% | -2.0779 | -7.4294% |
| 8 | 2023-09-23–2023-12-21 | 180/10/0.70 | 0.146209 | 0.4285% | 2.0707 | -0.0529% |
| 9 | 2023-12-22–2024-03-20 | 180/10/0.70 | 0.315082 | 1.6765% | 0.5161 | -6.7503% |
| 10 | 2024-03-21–2024-06-18 | 180/10/0.85 | 0.389413 | -3.0568% | -0.5549 | -9.7413% |
| 11 | 2024-06-19–2024-09-16 | 30/10/0.55 | 0.380961 | -1.2987% | -0.3333 | -5.8050% |
| 12 | 2024-09-17–2024-12-15 | 30/10/0.55 | 0.326855 | 6.8902% | 2.3211 | -4.4903% |
| 13 | 2024-12-16–2025-03-15 | 30/10/0.55 | 0.634247 | -5.8470% | -1.5956 | -7.9783% |
| 14 | 2025-03-16–2025-06-13 | 90/10/0.55 | 0.390055 | 1.9576% | 1.3723 | -2.0746% |
| 15 | 2025-06-14–2025-09-11 | 90/10/0.55 | 0.810081 | 4.3951% | 1.2193 | -4.3501% |
| 16 | 2025-09-12–2025-12-10 | 90/10/0.55 | 1.273300 | 1.1359% | 0.3689 | -7.5623% |
| 17 | 2025-12-11–2026-03-10 | 90/10/0.55 | 1.210265 | -1.2907% | -0.7599 | -3.4089% |
| 18 | 2026-03-11–2026-06-08 | 90/10/0.55 | 1.040312 | -6.1787% | -2.9208 | -8.4207% |

Fold stability passed its internal concentration gate: 9 of 18 folds were profitable, and the largest positive fold contributed 25.20% of total positive fold return. This did not rescue the aggregate result.

## Aggregate OOS result

| Metric | Strategy | Buy & hold | Vol-targeted long | Simple trend long/cash |
|---|---:|---:|---:|---:|
| Total return | -8.7433% | -70.6015% | -52.2529% | -8.1410% |
| CAGR | -2.0403% | -24.1057% | -15.3428% | -1.8950% |
| Sharpe | -0.0795 | 0.0108 | -0.0439 | 0.2178 |
| Calmar | -0.1096 | -0.3320 | -0.2434 | -0.0342 |
| Max drawdown | -18.6244% | -72.6136% | -63.0401% | -55.4906% |

The strategy's aggregate OOS return was -8.7433%, CAGR -2.0403%, Sharpe -0.0795, and maximum drawdown -18.6244%. The unchanged classifier therefore rejected the result at its first gate: aggregate return and Sharpe were non-positive.

At 2× costs, total return was -14.0522%; at 4× costs it was -23.7635%. Only the longer-lookback perturbation was profitable; the other three perturbations were negative.

## Paired moving-block bootstrap

- observed max-drawdown delta versus volatility-targeted long: `0.444157`;
- 95% interval: `[0.216166, 0.687049]`;
- probability delta > 0: `0.9995`;
- Calmar delta 95% interval: `[-0.536261, 0.601419]`;
- block length: 20; paired resamples: 2,000; confidence: 95%; seed: 20260722.

The drawdown improvement was statistically supported under the fixed bootstrap specification, but the strategy still lost money and failed the repository's robustness gate. This is evidence of lower exposure/path risk on LTC, not evidence of a deployable or return-positive strategy.

## Failure reasons and interpretation

1. Aggregate OOS total return and Sharpe were negative.
2. The result remained negative at 2× and 4× transaction costs.
3. Three of four parameter-neighbourhood perturbations had negative total return.
4. The strategy did not beat all tested benchmarks on return, Sharpe, or Calmar.
5. The predeclared joint rule required both robustness and drawdown-inference conditions; only the drawdown condition passed.

## Reproduction commands

These commands were executed by workflow run `29859059348` after the protocol commit:

```bash
python -m pip install --upgrade pip && python -m pip install -e ".[dev]"
ruff check . && ruff format --check .
pytest
python scripts/run_okx_research.py \
  --inst-id LTC-USDT \
  --output-dir reports/research/sealed-ltc-validation/LTC-USDT \
  --manifest-path reports/research/sealed-ltc-validation/experiment-manifest.jsonl
python scripts/run_bootstrap_research.py \
  --returns-csv reports/research/sealed-ltc-validation/LTC-USDT/walk_forward_returns.csv \
  --instrument LTC-USDT \
  --output-dir reports/research/sealed-ltc-validation/bootstrap \
  --block-length 20 \
  --resamples 2000 \
  --confidence 0.95 \
  --annualization 365 \
  --seed 20260722 \
  --source-run-id 29859059348 \
  --source-head-sha 1e5b0715f5b73ce36ca75ad23bd8fc1e9c08a2ad
```

Workflow installation, Ruff lint/format, full pytest, BTC/ETH rolling OOS research, sealed LTC walk-forward research, sealed LTC bootstrap, and artifact upload all completed successfully.

## Limits

- This is one sealed market and cannot establish universal generalisation.
- LTC history returned by OKX begins on 2020-01-02 despite a 2017 requested start; the pipeline recorded `requested_start_reached=false` and a complete short-page termination.
- The bootstrap evaluates observed OOS return paths and does not model order-book impact, latency, or capacity.
- LTC-USDT is now consumed as a holdout and must not be reused for same-market architecture tuning.
