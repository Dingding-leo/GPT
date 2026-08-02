from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected exactly one occurrence of {old!r}, found {count}")
    return text.replace(old, new)


def transform(text: str) -> str:
    critical_old = '''def leverage_statistic(returns: np.ndarray, response_indices: np.ndarray) -> float:
    antecedent = returns[response_indices - 1]
    subsequent_variance = returns[response_indices] ** 2
    if not np.isfinite(antecedent).all() or not np.isfinite(subsequent_variance).all():
        return float("nan")
    value = -corr(antecedent, subsequent_variance)
    return value if math.isfinite(value) else float("nan")
'''
    critical_new = '''def clustering_statistic(returns: np.ndarray, response_indices: np.ndarray) -> float:
    antecedent_variance = returns[response_indices - 1] ** 2
    subsequent_variance = returns[response_indices] ** 2
    if not np.isfinite(antecedent_variance).all() or not np.isfinite(subsequent_variance).all():
        return float("nan")
    value = corr(antecedent_variance, subsequent_variance)
    return value if math.isfinite(value) else float("nan")
'''
    text = replace_once(text, critical_old, critical_new)
    replacements = (
        (
            "causal-own-price-leverage-effect-relaxation-opportunity-1h-v1",
            "causal-own-price-volatility-clustering-relaxation-opportunity-1h-v1",
        ),
        (
            "accept_causal_own_price_leverage_effect_relaxation_information_premise_1h_v1",
            "accept_causal_own_price_volatility_clustering_relaxation_information_premise_1h_v1",
        ),
        (
            "reject_causal_own_price_leverage_effect_relaxation_information_premise_1h_v1",
            "reject_causal_own_price_volatility_clustering_relaxation_information_premise_1h_v1",
        ),
        ("SEED = 2026080223", "SEED = 2026080300"),
        ('"pair": "(r[i-1], r[i]^2)"', '"pair": "(r[i-1]^2, r[i]^2)"'),
        (
            '"leverage_statistic": "-corr(r[i-1],r[i]^2)"',
            '"clustering_statistic": "corr(r[i-1]^2,r[i]^2)"',
        ),
        (
            '"feature": "baseline_leverage-recent_leverage"',
            '"feature": "baseline_clustering-recent_clustering"',
        ),
        (
            "# Own-price leverage-effect relaxation opportunity diagnostic",
            "# Own-price volatility-clustering relaxation opportunity diagnostic",
        ),
        (
            "Bilateral leverage-effect relaxation support failed: ",
            "Bilateral volatility-clustering relaxation support failed: ",
        ),
        (
            "zero variance or non-finite leverage correlation",
            "zero variance or non-finite variance-clustering correlation",
        ),
        ("leverage_feature", "clustering_feature"),
        ("leverage_statistic", "clustering_statistic"),
        ("baseline_leverage", "baseline_clustering"),
        ("recent_leverage", "recent_clustering"),
        ("leverage_relaxation", "clustering_relaxation"),
    )
    for old, new in replacements:
        if old not in text:
            raise RuntimeError(f"required source fragment missing: {old!r}")
        text = text.replace(old, new)

    forbidden = (
        "leverage-effect",
        "leverage_effect",
        "leverage_feature",
        "leverage_statistic",
        "baseline_leverage",
        "recent_leverage",
        "leverage_relaxation",
        '"pair": "(r[i-1], r[i]^2)"',
        '"leverage_statistic":',
    )
    remaining = [fragment for fragment in forbidden if fragment in text]
    if remaining:
        raise RuntimeError(f"stale leverage diagnostic fragments remain: {remaining}")
    if text.count("clustering_relaxation") < 8:
        raise RuntimeError("transformed diagnostic has too few clustering-relaxation bindings")
    if "leverage_used" not in text:
        raise RuntimeError("hard-boundary leverage prohibition field was accidentally removed")
    return text


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    source = Path(args.input).read_text(encoding="utf-8")
    Path(args.output).write_text(transform(source), encoding="utf-8")


if __name__ == "__main__":
    main()
