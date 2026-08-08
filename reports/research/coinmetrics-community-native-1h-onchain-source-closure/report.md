# Coin Metrics Community native-1H on-chain source programme closure

Issue: #1131  
Family: `causal-coinmetrics-community-native-1h-onchain-source-programme-closure-v1`  
Candidate/grid: `0 / 0`  
New market rows / target labels / OOS / fitting: `0 / 0 / 0 / 0`

## Bound evidence

### A — base activity and fee-pressure source family (#1033)

- Exact head: `ff9033c753ff23198cda9b56480ac9a37921ac65`
- Workflow: `30793141251`
- Artifact ZIP SHA-256: `7acae07e142be39b0f8339ce7a6cdd663de4b12b5b0b3e5797ba1152a6fee516`
- Evidence SHA-256: `1d973dfeab8d989055f3bfac8180c1703d125d13d61d889ad8b8ee24200976e8`
- Result: TxCnt DOGE/LTC plus FeeTotUSD/FeeTotNtv BTC/ETH established no bilateral credential-free provider-native 1H source.
- Economics: unavailable and preserved as null.
- Terminal verdict: `reject_causal_public_onchain_activity_source_family_1h_v2`.

### B — transfer-size breadth (#1093 / PR #1095)

- Exact head: `a5c844710090a68f1edf66b6e33023a17f09e938`
- Workflow: `31244537171`
- Artifact: `9018098410`
- Artifact ZIP SHA-256: `37614c1c7a54486de3a6ccad79dbde45a2d48e4b56facf6877873191369a4861`
- Evidence SHA-256: `3c44aef6cb4574bc1b1bef1ec3777ec867d9bfd340271c135964c3e53b6d09d2`
- Result: BCH `TxTfrValMeanNtv / 1h` was not declared Community-available; rejected before target returns.
- Candidate/grid: `0 / 0`; sealed OOS unread.
- Terminal verdict: `reject_causal_onchain_transfer_size_breadth_source_contract_1h_v1`.

### C — active-address count (#1129 / PR #1130)

- Exact head: `e516f6f8c9a3ae70ed8935a6d1cd161453736011`
- Workflow: `31262239534`
- Artifact: `9023111171`
- Artifact ZIP SHA-256: `447b4f2185e5b435e2262188b53e297d07b059446caff7b39b59ce1204413884`
- Evidence SHA-256: `12a049ef38c54ec2aa0246d214846723cabd8c5fceffa692fe8dac943da088ea`
- Result: BTC/ETH `AdrActCnt` was catalogued at 1d, not 1h; all six frozen direct-1H probes returned HTTP 403.
- Candidate/grid: `0 / 0`; target candles, returns and OOS unread.
- Terminal verdict: `reject_causal_public_active_address_count_source_contract_1h_v1`.

## Closure adjudication

Independent admissible source groups: **0/3**.

Programme gates: **3/6 pass**. The three support gates fail: there is no complete bilateral native-1H source, no complete nonconstant bilateral source, and no group whose original protocol reached authorized target-return/economic adjudication. Null-accounting, source-feasibility-not-alpha discipline, and leave-one-group-out stability pass.

Leave-one-group-out:
- omit A -> 0 admissible groups;
- omit B -> 0 admissible groups;
- omit C -> 0 admissible groups.

The result is structural. Reopening adjacent Coin Metrics Community metrics, aliases, units, shorter windows or daily-to-hour reconstruction would be source/multiplicity hunting rather than alpha development. This closure does **not** claim on-chain information is economically useless; it closes the exact credential-free Community provider-native 1H programme and its direct rescue surface.

## Disposition

- correction authority: false
- canonical mutation: false
- observation-epoch restart: false
- paper trading: false
- live trading: false

Terminal verdict:

`reject_reopening_coinmetrics_community_native_1h_onchain_source_mechanisms_v1`

Evidence JSON SHA-256: `f1a8848cbf51e4800d4ed5d1dadcd1221572fd59b997ffc7d50602a1180a714e`
