# Terminal evidence amendment

This amendment is authoritative for the final compact deterministic reproducer and supersedes only the stale evidence-identity block in `report.md`. The strategy, immutable data, samples, positions, returns, fee model, metrics, bootstrap draws, gates, failure diagnosis, and rejection verdict are unchanged.

The final reproducer validates full-source SHA-256, 43,994 source rows per market, the first 43,441 contiguous confirmed 1H rows, completed-bar/next-open timing, exactly 5 bps one-way fees, and future-suffix invariance. It writes standards-compliant JSON with no NaN or infinity values and separately accounts for SOL's 23-hour boundary-open sleeve.

```text
Protocol SHA-256             df10154d7106b2ee10533d7ae10b867fcdcb72399d361e785d393d2e5dbc6271
Final reproducer SHA-256     108d8a5874f4793f62ba3b3e02190d15b07ff277ff1fcaafdd6e5dbd978e37e1
Reproduced result SHA-256    d232616f06b2a6fecdd91fc39693f57bf2feb494b374af369743ad7d73f14dc0
Canonical result payload     9709c2f7fb9bb05f2d227901cdde16850cd5dc3c9247d181145c9e4d117c1726
SOL raw frozen-prefix SHA    4c547f718cf7d96387a90917b7508442e34887119973e1555386cadd599a4aa3
XRP raw frozen-prefix SHA    72209c2d5abda9c31722a51b3b0e70bd656099fcc071af0700ba1704e081e45d
Verdict                      reject_beta_sign_soft_exit_sleeve_family
```

Two complete executions of the final reproducer were byte-identical. The compact result reproduces the terminal report's train, development-OOS, full-sample, benchmark, turnover, drawdown, fold/year breadth, episode attribution, and 5,000-block uncertainty statistics.
