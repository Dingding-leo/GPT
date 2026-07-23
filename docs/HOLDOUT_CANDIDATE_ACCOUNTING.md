# Fixed-holdout candidate accounting

This page defines how the fixed validation/sealed-holdout path counts candidate formulas. It complements [`OKX_RESEARCH_CONFIG.md`](OKX_RESEARCH_CONFIG.md); it does not change the candidate grid or authorize retuning on the sealed holdout.

## Why this boundary matters

Repeated entries in a configuration array are not additional independent trials. Counting them as separate candidates would overstate the search space, distort ranking evidence, and misstate multiple-testing exposure.

`run_holdout_research()` therefore applies this order:

1. validate every declared momentum lookback, reversal lookback, and trend weight using the strict types and ranges documented in [`OKX_RESEARCH_CONFIG.md`](OKX_RESEARCH_CONFIG.md);
2. normalize valid values to their runtime integer or floating-point representation;
3. remove repeats within each dimension while preserving the first declared occurrence;
4. construct the Cartesian product from those distinct dimensions;
5. evaluate every distinct formula on the validation block;
6. retain only candidates with a finite selection score for `candidates_tested` and `candidate_ranking`;
7. persist at most `top_candidates` ranking entries without reducing the search itself.

Consequently, duplicate declarations cannot increase `candidates_tested` or create repeated ranking entries. The distinct-grid size is:

```text
len(unique(momentum_lookbacks))
× len(unique(reversal_lookbacks))
× len(unique(trend_weights))
```

`candidates_tested` cannot exceed that value and can be smaller only when a distinct candidate produces a non-finite selection score. It must never be reported as the product of the raw array lengths when those arrays contain repeats.

## Ordering and ties

Deduplication preserves the first occurrence in each candidate dimension. Python's stable score ordering therefore preserves first-declared distinct-formula order when selection scores tie.

For example:

```json
{
  "momentum_lookbacks": [42, 21, 42],
  "reversal_lookbacks": [3, 3],
  "trend_weights": [0.7, 0.7]
}
```

contains two distinct formulas, not six. If their selection scores tie, the momentum ordering remains `42`, then `21`; the repeated `42` is not a third candidate.

This ordering rule is deterministic, but declaration order must not be used to imply economic superiority. A tie remains a tie in validation evidence.

## Current repository configuration

The current `config/okx_holdout.json` contains three distinct values in each dimension, so its distinct grid is `3 × 3 × 3 = 27`. `top_candidates: 10` limits only the persisted ranking to at most ten entries; it does not reduce the 27-formula search when all scores are finite.

Audit the raw and distinct dimension sizes with this command, which is copyable in Bash and PowerShell:

```bash
python -c "import json; from pathlib import Path; s=json.loads(Path('config/okx_holdout.json').read_text(encoding='utf-8'))['search']; names=('momentum_lookbacks','reversal_lookbacks','trend_weights'); raw=[len(s[n]) for n in names]; distinct=[len(dict.fromkeys(s[n])) for n in names]; print({'raw_dimensions': raw, 'distinct_dimensions': distinct, 'distinct_grid': distinct[0]*distinct[1]*distinct[2], 'top_candidates': s['top_candidates']})"
```

Expected current output:

```text
{'raw_dimensions': [3, 3, 3], 'distinct_dimensions': [3, 3, 3], 'distinct_grid': 27, 'top_candidates': 10}
```

A changed output identifies a changed experiment declaration. It does not by itself prove that every distinct candidate produced a finite score; reconcile the generated report's `candidates_tested` and `candidate_ranking` as well.

## Executable verification

Run the core real-OKX regression and the documentation binding:

```bash
pytest -q \
  tests/test_holdout_candidate_deduplication.py \
  tests/test_holdout_candidate_accounting_documentation.py
```

These tests use the repository's immutable real OKX BTC-USDT fixture. They do not generate or simulate market prices, and duplicated declarations are used only to verify accounting and deterministic ordering.
