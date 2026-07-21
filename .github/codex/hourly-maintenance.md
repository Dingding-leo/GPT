# Hourly maintenance task

You are maintaining **GPT Quant Lab**, a reproducible and auditable quantitative-research codebase.

Make **at most one** small, high-confidence improvement in this run. The result must be easy for a human to review. If no safe and useful change is available, leave the repository unchanged and explain why.

## Read first

Inspect the current `README.md`, recent git history, `src/`, `scripts/`, and `tests/` before choosing work. Treat the repository's research discipline as a hard requirement, not as documentation-only guidance.

## Priority order

1. Correctness bugs, especially look-ahead, timestamp alignment, fold isolation, turnover, costs, and state carried across evaluation boundaries.
2. Deterministic regression tests for important behavior that is currently untested.
3. Input validation, data provenance, reproducibility, and failure diagnostics.
4. Statistically honest evaluation and benchmark comparisons.
5. Small maintainability or documentation improvements only when they support concrete behavior.

Prefer work that is independent of unresolved choices about market, vendor, credentials, or live execution.

## Hard constraints

- Never add live trading, order placement, account access, leverage, credential handling, or broker/exchange write endpoints.
- Do not optimize parameters because a backtest looks better, weaken rejection criteria, or present synthetic-data results as alpha.
- Do not edit anything under `.github/`, dependency or packaging files, `AGENTS.md`, `config/`, `data/`, or `reports/`.
- Do not add or update dependencies.
- Do not use the network or download market data. Tests must remain deterministic and offline.
- Do not remove, skip, loosen, or rewrite tests merely to make them pass.
- Avoid broad refactors, public-API churn, generated artifacts, notebooks, and binary files.
- Keep the change to no more than 8 files and roughly 300 changed lines.
- Preserve backward compatibility unless fixing an unambiguous correctness defect; document any intentional behavior change.

## Required workflow

1. Identify one concrete deficiency and state the invariant that should hold.
2. Add or strengthen a focused test that would fail without the improvement.
3. Implement the smallest complete fix.
4. Run:
   - `ruff check .`
   - `ruff format --check .`
   - `pytest`
   - `python scripts/run_research.py --output-dir /tmp/gpt-quant-hourly-report`
5. Review the final diff for accidental generated files, unrelated formatting, hidden future-data access, and misleading research claims.
6. Leave the working tree unchanged if the proposed improvement cannot pass every required check.

## Final response

Summarize:

- the problem and invariant;
- the exact files and behavior changed;
- commands run and their results;
- residual risks or follow-up work.
