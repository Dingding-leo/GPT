# Exact-head strategy audit

```text
family_id       transaction-cost-aware-online-specialist-arbitration-1h-v1
candidate_count 1
parameter_grid  0
fee_one_way     0.0005
verdict         reject_transaction_cost_aware_online_specialist_arbitration_architecture_v1
```

The only post-performance repair is evidence-serialization correctness: `evidence.sha256` now hashes the exact newline-terminated bytes written to `evidence.json`, and the workflow verifies that identity before persistence. No source candle, boundary, specialist signal, utility update, decay, switching penalty, dwell rule, execution timestamp, fee, return, fold, bootstrap draw, metric, gate, or verdict changed.

The strategy-facing failure is not fee burden. On RUNEUSDT, online arbitration beat all three static specialists at the OOS point estimate, but only three of six folds were positive, 74.33% of positive-fold profit came from one fold, and the paired confidence interval versus E2160 crossed zero. On KAVAUSDT, only five of sixteen OOS identity switches improved the following 168-hour utility; mean switch improvement was -3.19%, and the candidate lost 46.69% OOS versus +16.12% for static E1440. The candidate's KAVA deficit versus E1440 was approximately 63.61 percentage points of gross timing and only 0.80 percentage points of relative fee drag. This rejects lagged net-utility specialist chasing as a robust cross-market selector rather than identifying a transaction-cost tuning problem.

No same-cohort change to expert horizons, memory, switching penalty, dwell, tie order, cadence, market subset, or acceptance gate is authorised.