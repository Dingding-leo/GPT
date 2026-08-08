# Lagged cross-market price risk-appetite programme closure

## Scope

This report closes only the already-completed lagged public cross-market **price-derived** risk-appetite mechanisms bound by issue #1074. It acquires no new market row, computes no new target label, opens no sealed sample, fits no statistic and creates no executable candidate.

```text
family_id                  causal-lagged-cross-market-price-risk-appetite-programme-closure-1h-v1
candidate_count            0
parameter_grid_count       0
new_market_data_rows       0
new_target_labels          0
new_OOS_access             0
new_fitting_or_tuning      0
canonical_mutation         false
paper/live                 false
```

Each evidence unit is judged only against the acceptance contract that governed it when the data were first inspected. Missing economics from zero-candidate information diagnostics remain unavailable rather than being coerced to zero.

## Immutable transfer matrix

| Evidence unit | Mechanism | Original targets/cohorts | Original support | Decisive failure | Independently admissible |
|---|---|---|---|---|---|
| #877 | lagged BTC stress/liquidity entry-gating family | BTC-USDT, ETH-USDT | 0/3 submechanisms | BTC downside-stress veto trailed B1 and had negative paired lower bounds; ETH lower bounds were zero; breadth was 5/12 and 6/12 with effect concentrated in one fold; recovery state vanished OOS; shock-absorption support was 6 vs required 20 | No |
| #963 | fixed equal-weight lagged directional diffusion | BTC-USDT, ETH-USDT | 0/2 targets | all dependence intervals crossed zero; adverse tercile effects were negative; fold breadth and delayed adverse transport failed bilaterally | No |
| #1072 | lagged OKB 24H risk-appetite impulse | HBAR-USDT, CHZ-USDT | 0/2 targets | fee-adjusted return associations were negative in both targets; CHZ dependence intervals were strictly negative for net and adverse slopes; one-hour delay remained adverse | No |

### #877 — lagged BTC entry gating

Exact evidence: head `aebc76c933438ff4f5237c50bd0d86f0ed93c095`, workflow `30700411497`, artifact `8818626935`.

The only executable source experiment, downside-stress veto, produced BTC OOS `+115.3669% / 0.9346 Sharpe` versus B1 `+119.6820% / 0.9538`, while ETH produced `+86.7749% / 0.6974` versus B1 `+74.5160% / 0.6456`. The BTC paired lower bounds were negative (`-0.023288` annualised mean delta; `-0.066460` Sharpe delta), ETH lower bounds were zero, positive-relative breadth was only `5/12` BTC and `6/12` ETH, and the selector effect was concentrated in one fold per market. The liquidity-stress recovery state fell from `16.5574%` in training to `0%` OOS; downside-shock absorption had only six training decisions from one event against a support floor of 20. Original verdict: `reject_causal_lagged_btc_entry_gating_family`.

### #963 — fixed-universe directional diffusion

Exact evidence: head `275d04f5c0f58bbaa55791c54a2eff7ed278f268`, workflow `30743127268`, artifact `8832088828`. Candidate/grid remained `0/0`; sealed OOS and strategy performance were not opened.

BTC had 286 opportunities and small positive point estimates (`rho/slope +0.020240/+0.030843` net, `+0.020559/+0.018898` adverse) but only `1/4` positive net-slope folds and `2/4` adverse folds. ETH had 242 opportunities (`+0.046307/+0.082941` net; `+0.020492/+0.029335` adverse), but adverse upper-minus-lower tercile effect was `-0.198952%`, only `2/4` adverse folds were positive and positive net-slope contribution concentration was `71.74%`. Every frozen moving-block dependence interval crossed zero. The one-hour-delay replay failed bilateral adverse transport. Original verdict: `reject_causal_fixed_universe_directional_diffusion_information_premise_1h_v1`.

### #1072 — lagged OKB impulse

Exact evidence: head `8ed0096b485f75b5633cd7940776b7f4bcf0cd14`, workflow `31234027573`, artifact `9014955096`. Candidate/grid remained `0/0`; sealed OOS and executable performance remained unopened.

HBAR retained 249 opportunities but net Spearman/slope were `-0.055980/-0.005153` and the return tercile effect was `-148.84 bp`. CHZ retained 199 opportunities with net `-0.072686/-0.006884`, adverse `-0.053382/-0.004364`, and return/adverse tercile effects `-122.52/-45.33 bp`. CHZ moving-block standardized-slope intervals were entirely negative: net `[-0.013441,-0.001171]`, adverse `[-0.008188,-0.000044]`. The one-hour-delay replay remained negative for both targets. Original verdict: `reject_causal_lagged_okb_risk_appetite_opportunity_information_premise_1h_v1`.

## Frozen adjudication

No bound mechanism passed all of its own original economic/information, downside, breadth, dependence, execution-delay, support/concentration and bilateral/cohort gates. Therefore independently admissible mechanisms are `0/3`.

Leave-one-mechanism-out does not change the conclusion: removing #877, #963 or #1072 still leaves zero independently admissible mechanisms. Leave-one-cohort-out cannot create support because each original protocol required bilateral/cohort passage and explicitly prohibited single-market promotion. There is therefore no supportive conclusion that can survive the closure's transport condition.

## Terminal disposition

```text
verdict
reject_reopening_completed_lagged_cross_market_price_risk_appetite_mechanisms_1h_v1

correction_authority            false
canonical_policy_changed        false
observation_epoch_restarted     false
paper_trading_authorized        false
live_trading_authorized         false
```

Closed rescue scope includes alternate lagged scalar signs, horizons, windows, volatility normalizers, BTC/OKB/other-token substitution as another generic price-risk proxy, panel-member deletion or weighting, target-relative/current-rank transforms, threshold search, favourable-fold deletion, single-market promotion and combinations of the rejected BTC-stress, directional-diffusion and OKB-impulse mechanisms.

Any successor must introduce materially new information rather than another lagged scalar cross-market price-risk-appetite transform, while remaining causal 1H and same-target unlevered long/cash.
