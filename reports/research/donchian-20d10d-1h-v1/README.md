# Fixed 20d/10d Donchian long/cash 1H training rejection

Issue: #1117

## Frozen objective

Test exactly one causal own-price strategy: enter long after a completed 1H close exceeds the prior 480H high, exit to cash after a completed 1H close falls below the prior 240H low, and execute each target change at the next observed hourly open. Position is unlevered binary long/cash and every one-way position change costs exactly 5 bps. No parameter grid, market ranking, target filtering, or B1-superiority gate is used.

## Immutable data and access discipline

- BTC-USDT: public OKX SPOT completed 1H artifact `8704977298`; CSV SHA-256 `92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9`.
- ETH-USDT: public OKX SPOT completed 1H artifact `8704978112`; CSV SHA-256 `2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726`.
- Frozen training segment: `[2880,17520)`, 2021-11-21 00:00 UTC through 2023-07-23 23:00 UTC.
- The evaluator parses only rows `0..17520`, where row `17520` supplies the exclusive-end next-open boundary. It never parses a development-OOS return.
- Development OOS `[17520,43440)` and full-sample strategy metrics remain null because the bilateral training gate failed.
- Source checks require exact hash, unique monotone contiguous UTC-hour timestamps, confirmed rows, finite positive OHLC, valid candle bounds, exact source start, and exact training boundary.

The executable accounting starts every scored segment from cash, uses open-to-next-open asset returns, applies a target only after the completed signal bar, charges 5 bps on every one-way transition, and charges terminal liquidation at the exclusive segment endpoint when still long.

## Training result

| Market | Net return | Ann. mean | Sharpe | Max DD | Exposure | Turnover | Transitions | Fee drag | Edge / turnover |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | **-27.0132%** | -14.3819% | **-0.4819** | -45.7417% | 34.1530% | 24 | 24 | 1.20% | **-100.15 bp** |
| ETH-USDT | **-14.6875%** | -2.8138% | **-0.0769** | -36.4221% | 33.3538% | 22 | 22 | 1.10% | **-21.38 bp** |

The frozen descriptive E2160 training reference was also negative: BTC `-41.2906% / -0.8403` Sharpe and ETH `-40.5888% / -0.5842`. Donchian loses less than that historical comparator, but this is not an acceptance criterion and cannot rescue negative absolute economics.

## Temporal breadth

The six preregistered start-anchored 2,160H training folds produced:

| Market | Positive folds | Fold returns |
|---|---:|---|
| BTC-USDT | **2/6** | -17.10%, +1.26%, -10.88%, -19.25%, +22.98%, -2.26% |
| ETH-USDT | **3/6** | -14.59%, +1.62%, +34.82%, -14.05%, +8.06%, -3.33% |

Largest positive-fold contribution was **94.81%** for BTC and **78.25%** for ETH, both above the frozen 60% concentration ceiling.

Training calendar-year slices, each restarted from cash, were:

| Market | 2021 available slice | 2022 | 2023 available slice | Positive years |
|---|---:|---:|---:|---:|
| BTC-USDT | -11.90% | -38.41% | +34.52% | **1/3** |
| ETH-USDT | 0.00% | -18.15% | +4.23% | **1/3** |

As an ambiguity check only, anchoring six complete 2,160H folds to the training endpoint instead of the start also fails breadth: BTC `2/6`, ETH `1/6`. No fold anchoring can change the terminal verdict because aggregate training return and Sharpe are already negative bilaterally.

## Dependence-aware uncertainty

Five thousand non-circular 168H moving-block resamples were run separately per market with seed `2026080821`, resampling only observed real net hourly returns.

- BTC annualized arithmetic-mean 95% lower endpoint: **-62.60%**; Sharpe lower endpoint: **-2.1305**.
- ETH annualized arithmetic-mean 95% lower endpoint: **-61.26%**; Sharpe lower endpoint: **-1.7417**.

The bootstrap medians remain negative in both markets: BTC `-15.03% / -0.5006` Sharpe and ETH `-3.61% / -0.0996`.

## Mandatory +1H execution delay

The stress keeps the original signal timestamps and state machine but executes every target change one additional completed hour later.

| Market | Delayed net return | Delayed Sharpe | Delayed max DD | Delayed edge / turnover |
|---|---:|---:|---:|---:|
| BTC-USDT | **-23.5280%** | **-0.3890** | -43.4648% | -80.76 bp |
| ETH-USDT | **-13.7969%** | **-0.0604** | -37.2337% | -16.76 bp |

Latency therefore does not rescue the premise.

## Frozen gate vector

Both markets pass only source/accounting integrity, the `>-50%` drawdown ceiling, prefix-bounded evaluation, and the no-post-hoc-selection rule. Both fail:

- positive training return and Sharpe;
- edge per turnover above 10 bps;
- at least 4/6 positive folds;
- at least 2/3 positive years;
- positive-fold concentration at or below 60%;
- positive 95% moving-block lower bounds for annualized mean and Sharpe;
- positive return and Sharpe after the mandatory +1H delay.

Because the bilateral training gate fails, development OOS is not evaluated and no full-sample equity curve is constructed.

## Reproducibility

Executed command:

```bash
python scripts/run_donchian_20d10d_research.py \
  --btc-csv <artifact-8704977298>/snapshot/okx-BTC-USDT-1H.csv \
  --eth-csv <artifact-8704978112>/snapshot/okx-ETH-USDT-1H.csv \
  --output reports/research/donchian-20d10d-1h-v1/evidence.json
```

- script SHA-256: `5d7900804ef28d21c2f7e6323d7c63ff350410d7516847efc5275ba7f98316e5`
- evidence JSON SHA-256: `66542f5c50323c34d0f01b77104bfdb68f4f54aaa839d6e8559552c2ec9bbdf4`
- candidate count: `1`
- parameter grid count: `0`
- bootstrap draws: `5,000` per market
- synthetic/generated market data: `0`
- credentials/private endpoints/accounts/orders/leverage: `0`

## Verdict

```text
reject_causal_own_price_donchian_20d10d_training_economics_1h_v1
```

This is a training-stage rejection, not evidence that all channel-breakout concepts are impossible. It does close the exact 480H-entry/240H-exit long/cash rule on this consumed BTC/ETH cohort. No alternate channel length, ATR filter, stop, close/high variant, cooldown, market subset, or sign reversal is authorized from these results.
