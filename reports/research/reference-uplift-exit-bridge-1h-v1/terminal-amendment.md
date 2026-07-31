# Terminal diagnostic amendment

The strategy outputs are unchanged. Event-level attribution was added after inspecting the failure mechanism.

- BCH selected 6 of 27 completed OOS exits; selected targets summed to -1.5275%, with 2/6 positive. Rejected targets summed to +13.6455%, with 13/21 positive.
- LINK selected 1 of 17 completed OOS exits. The 2023-10-19 bridge contributed +10.9000% and accounts for the entire OOS arithmetic residual.
- Boundary partial attribution is exactly zero in both markets.
- Exit-decomposition identity error is below 2.6e-16.
- A local rerun from the immutable CSVs and acquisition record reproduced `result.json` byte-for-byte.

No signal, position, return, fee, turnover, drawdown, fold/year result, bootstrap draw, gate, or verdict changed.
