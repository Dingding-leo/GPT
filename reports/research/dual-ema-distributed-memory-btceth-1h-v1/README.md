# Dual-EMA distributed-memory trend canonical BTC/ETH replication

Frozen family: `causal-own-price-dual-ema-distributed-memory-trend-canonical-replication-1h-v1`

Training-only disposition under issue #1120. Development OOS `[17520,43440)` was not opened because the bilateral training gate failed.

## Frozen data and rule

- BTC-USDT artifact `8704977298`, CSV SHA-256 `92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9`.
- ETH-USDT artifact `8704978112`, CSV SHA-256 `2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726`.
- Parsed only rows `[0,17521)`: warm-up `[0,4320)`, training `[4320,17520)`, row `17520` only for the exclusive-end next open.
- Signal: recursive log-price EMA(720H) minus EMA(2160H), target long iff score > 0, evaluated at UTC 00:00 using `t-1`, executed at `open[t]`.
- Fees: exactly 5 bps one way on every exposure transition and terminal liquidation.
- Candidate/grid: `1/0`.
- Development OOS and full performance: unread/null.

## Training economics

### BTC-USDT

- Candidate: net `+25.345469%`, Sharpe `+0.675876`, MDD `-21.731535%`, turnover `4`, fees `0.2000%`, edge/turn `+712.56 bp`.
- 2,160H folds: `2/6` positive; positive-fold contribution concentration `93.76%`.
- Calendar slices represented: 2022 `-13.778211%`, 2023 `+45.375629%`; `1/2` positive.
- 5,000×168H moving-block q2.5: annualized mean `-29.638046%`, Sharpe `-1.111811`.
- +1H execution delay: net `+23.287450%`, Sharpe `+0.636863`, edge/turn `+670.98 bp`.
- Descriptive E2160 training: `-8.591808%`, Sharpe `-0.052527`.
- Always-long training: `-27.859088%`, Sharpe `-0.081136`.

BTC therefore has a favorable aggregate point estimate but fails the frozen fold-breadth, calendar-breadth, concentration and dependence-aware lower-bound gates.

### ETH-USDT

- Candidate: net `-29.936398%`, Sharpe `-0.510792`, MDD `-48.856161%`, turnover `8`, fees `0.4000%`, edge/turn `-332.02 bp`.
- 2,160H folds: `1/6` positive; positive-fold contribution concentration `100%`.
- Calendar slices represented: 2022 `-41.451202%`, 2023 `+19.667021%`; `1/2` positive.
- 5,000×168H moving-block q2.5: annualized mean `-68.482574%`, Sharpe `-1.936672`.
- +1H execution delay: net `-27.813964%`, Sharpe `-0.454774`, edge/turn `-295.10 bp`.
- Descriptive E2160 training: `-26.786962%`, Sharpe `-0.394298`.
- Always-long training: `-38.830207%`, Sharpe `-0.060523`.

ETH fails positive aggregate training economics, turnover efficiency, temporal breadth, concentration, dependence-aware support and delay transport.

## Terminal verdict

The bilateral training gate is false. Development OOS remains unread and full metrics remain null.

`reject_causal_own_price_dual_ema_distributed_memory_trend_canonical_replication_training_1h_v1`

No span change, EMA/MACD rescue, target deletion, threshold, hysteresis, volatility filter, sign reversal, policy mutation, paper trading or live trading is authorized.
