# Fixed dual-EMA distributed-memory trend — BTC/ETH 1H training rejection

Issue: #1120

## Frozen objective

Test one causal own-price long/cash architecture on immutable public OKX SPOT 1H data. The signal is the sign of a 720H EMA minus a 2160H EMA of hourly log close, both recursively initialised from row zero. At each UTC 00:00 anchor, only data through `close[t-1]` are used and the resulting binary target is applied at `open[t]`. Every one-way exposure change costs exactly 5 bps. There is one architecture candidate and no parameter grid.

The frozen discipline requires bilateral BTC-USDT and ETH-USDT training passage before any development-OOS strategy row may be parsed. The bilateral training gate fails, so OOS and full strategy metrics remain null.

## Immutable data and sample

- BTC-USDT artifact `8704977298`; CSV SHA-256 `92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9`.
- ETH-USDT artifact `8704978112`; CSV SHA-256 `2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726`.
- Parsed source prefix for this training run: rows `0..17520`, where row `17520` is only the exclusive-end next-open boundary.
- EMA warm-up: `[0,4320)`.
- Training: `[4320,17520)` = 13,200 scored hourly observations.
- Sealed development OOS: `[17520,43440)` — unread for strategy performance.
- One-way fee: `0.0005` on each exposure change and terminal liquidation.

Exact source hashes, completed-bar status, finite positive OHLC, UTC-hour continuity, unique ordering and the fixed training boundary are validated before strategy accounting.

## Training economics

| Market | Candidate net | Sharpe | Max DD | Exposure | Turnover | Fee drag | Edge / turnover |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | **+25.3455%** | **+0.6759** | -21.7315% | 36.1818% | 4 | 0.20% | **+712.56 bp** |
| ETH-USDT | **-29.9364%** | **-0.5108** | -48.8562% | 41.4545% | 8 | 0.40% | **-332.02 bp** |

BTC demonstrates that the distributed-memory representation can produce a low-turnover positive training path in one market. ETH rejects bilateral transport: the same frozen rule has negative return, negative Sharpe and negative edge per turnover.

## Descriptive benchmark comparison

E2160 is descriptive only after #1114 and cannot accept or reject this candidate.

| Market | EMA candidate | E2160 | Always long |
|---|---:|---:|---:|
| BTC-USDT net / Sharpe | **+25.35% / +0.6759** | -8.59% / -0.0525 | -27.86% / -0.0811 |
| ETH-USDT net / Sharpe | **-29.94% / -0.5108** | -26.79% / -0.3943 | -38.83% / -0.0605 |

The BTC result is economically stronger than both descriptive comparators in training. ETH is weaker than E2160 on both return and Sharpe and remains negative in absolute terms.

## Temporal breadth

Six complete start-anchored 2,160H training folds, each restarted from cash:

- BTC: `2/6` positive; returns `[-13.78%, 0.00%, 0.00%, 0.00%, +47.24%, +3.14%]`; largest positive-fold contribution `93.76%`.
- ETH: `1/6` positive; returns `[-12.02%, -3.16%, -31.35%, 0.00%, +33.02%, -4.63%]`; largest positive-fold contribution `100.00%`.

The frozen training interval intersects only calendar years 2022 and 2023. The issue's threshold is therefore operationalised literally as requiring at least two positive represented restarted-from-cash calendar slices. Both markets have only one positive slice:

- BTC: 2022 `-13.78%`, 2023 `+45.38%` => `1/2` positive.
- ETH: 2022 `-41.45%`, 2023 `+19.67%` => `1/2` positive.

This denominator ambiguity cannot affect the rejection because both markets already fail fold breadth, concentration and dependence support, while ETH also fails aggregate economics and delay transport.

## Dependence-aware uncertainty

5,000 non-circular 168H moving-block draws of observed training net hourly returns were run independently with the frozen seeds.

| Market | Seed | Ann. mean q2.5 | Ann. mean median | Sharpe q2.5 | Sharpe median |
|---|---:|---:|---:|---:|---:|
| BTC-USDT | 2026080822 | **-29.6380%** | +17.7521% | **-1.1118** | +0.6431 |
| ETH-USDT | 2026080823 | **-68.4826%** | -17.0624% | **-1.9367** | -0.4915 |

Neither market has a strictly positive 95% lower bound for annualized arithmetic mean or Sharpe. BTC's attractive aggregate point estimate is therefore not dependence-supported under the preregistered block specification.

## Mandatory +1H execution transport

The original daily target sequence is preserved while every target change is delayed exactly one additional hour.

| Market | Delayed net | Delayed Sharpe | Delayed DD | Delayed edge / turnover |
|---|---:|---:|---:|---:|
| BTC-USDT | **+23.2874%** | **+0.6369** | -21.7315% | **+670.98 bp** |
| ETH-USDT | **-27.8140%** | **-0.4548** | -48.0105% | **-295.10 bp** |

BTC survives the latency stress; ETH does not.

## Gate verdict

BTC passes aggregate return/Sharpe, drawdown, turnover efficiency and +1H transport, but fails fold breadth, calendar breadth, positive-fold concentration and dependence lower bounds. ETH passes only source/accounting integrity and the `>-50%` drawdown ceiling among the economically material gates; it fails aggregate return/Sharpe, edge per turnover, breadth, concentration, dependence support and +1H transport.

The bilateral training gate is therefore false. Development OOS `[17520,43440)` remains unread and full/OOS strategy performance is null rather than zero.

```text
reject_causal_own_price_dual_ema_distributed_memory_trend_canonical_replication_training_1h_v1
```

## Reproducibility

```bash
python scripts/run_dual_ema_btc_eth_research.py \
  --btc-csv <artifact-8704977298>/snapshot/okx-BTC-USDT-1H.csv \
  --eth-csv <artifact-8704978112>/snapshot/okx-ETH-USDT-1H.csv \
  --output reports/research/dual-ema-canonical-replication-1h-v1/evidence.json
```

- runner SHA-256: `466fd91c750f7f306de4f34d9f4031098deb6fd47b6039205fc1cee1df45730a`;
- evidence JSON SHA-256: `7022ebade4d825aeee4db45a3de40dde67ffeed54098cab788d37a91ea6afa60`;
- candidate count: `1`;
- parameter-grid count: `0`;
- moving-block draws: `5,000` per market;
- synthetic/generated market rows: `0`;
- credentials/private endpoints/accounts/orders/leverage: `0`.

No alternate span, EMA initialisation, threshold, sign, phase, hysteresis, market subset, volatility filter or post-hoc combination is authorised from this consumed cohort.
