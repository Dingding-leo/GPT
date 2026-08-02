from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected exactly one occurrence of {old!r}, found {count}")
    return text.replace(old, new)


def replace_section(text: str, start: str, end: str, replacement: str) -> str:
    start_index = text.find(start)
    if start_index < 0:
        raise RuntimeError(f"section start missing: {start!r}")
    end_index = text.find(end, start_index)
    if end_index < 0:
        raise RuntimeError(f"section end missing after {start!r}: {end!r}")
    return text[:start_index] + replacement.rstrip() + "\n\n\n" + text[end_index:]


def transform(text: str) -> str:
    text = replace_section(
        text,
        "def leverage_statistic(",
        "def first_daily_anchor()",
        '''def _asymmetry_from_sequence(sequence: np.ndarray) -> tuple[float, float]:
    if len(sequence) < 2 or not np.isfinite(sequence).all():
        return float("nan"), float("nan")
    previous = sequence[:-1]
    current = sequence[1:]
    scale = math.sqrt(float(np.mean((previous * previous + current * current) / 2.0)))
    if not math.isfinite(scale) or scale <= 0:
        return float("nan"), float("nan")
    numerator = float(np.mean(previous * current * (current - previous)))
    value = numerator / (scale**3)
    return (value, scale) if math.isfinite(value) else (float("nan"), scale)


def asymmetry_statistic(returns: np.ndarray, response_indices: np.ndarray) -> dict[str, Any]:
    if len(response_indices) == 0 or not np.array_equal(
        response_indices,
        np.arange(response_indices[0], response_indices[-1] + 1, dtype=int),
    ):
        return {"valid": False, "reason": "response indices are not one contiguous sequence"}
    sequence = returns[response_indices[0] - 1 : response_indices[-1] + 1]
    if len(sequence) != len(response_indices) + 1:
        return {"valid": False, "reason": "return sequence has incorrect length"}
    forward, scale = _asymmetry_from_sequence(sequence)
    reverse, reverse_scale = _asymmetry_from_sequence(sequence[::-1])
    values = (forward, scale, reverse, reverse_scale)
    if not all(math.isfinite(value) for value in values):
        return {"valid": False, "reason": "non-finite asymmetry statistic or scale"}
    scale_error = abs(reverse_scale - scale)
    scale_tolerance = 1e-12 + 1e-10 * max(abs(scale), abs(reverse_scale))
    reverse_error = abs(reverse + forward)
    reverse_tolerance = 1e-12 + 1e-10 * max(abs(forward), abs(reverse))
    identity_passed = scale_error <= scale_tolerance and reverse_error <= reverse_tolerance
    return {
        "valid": identity_passed,
        "reason": None if identity_passed else "reverse-order antisymmetry identity failed",
        "value": forward,
        "scale": scale,
        "reverse_value": reverse,
        "reverse_scale": reverse_scale,
        "reverse_identity_error": reverse_error,
        "reverse_identity_tolerance": reverse_tolerance,
        "reverse_scale_error": scale_error,
        "reverse_scale_tolerance": scale_tolerance,
        "reverse_identity_passed": identity_passed,
    }


def asymmetry_feature(returns: np.ndarray, t: int) -> dict[str, Any]:
    baseline_indices = np.arange(t - 912, t - 192, dtype=int)
    recent_indices = np.arange(t - 192, t - 24, dtype=int)
    if len(baseline_indices) != BASELINE_PAIRS:
        raise ValueError("baseline does not contain exactly 720 response pairs")
    if len(recent_indices) != RECENT_PAIRS:
        raise ValueError("recent window does not contain exactly 168 response pairs")
    baseline = asymmetry_statistic(returns, baseline_indices)
    recent = asymmetry_statistic(returns, recent_indices)
    if not baseline["valid"] or not recent["valid"]:
        reasons = [record["reason"] for record in (baseline, recent) if not record["valid"]]
        return {"valid": False, "reason": "; ".join(str(reason) for reason in reasons)}
    feature = float(recent["value"] - baseline["value"])
    if not math.isfinite(feature):
        return {"valid": False, "reason": "non-finite recent-minus-baseline asymmetry shift"}
    return {
        "valid": True,
        "baseline_asymmetry": float(baseline["value"]),
        "recent_asymmetry": float(recent["value"]),
        "time_reversal_asymmetry_shift": feature,
        "baseline_scale": float(baseline["scale"]),
        "recent_scale": float(recent["scale"]),
        "baseline_reverse_value": float(baseline["reverse_value"]),
        "recent_reverse_value": float(recent["reverse_value"]),
        "baseline_reverse_identity_error": float(baseline["reverse_identity_error"]),
        "recent_reverse_identity_error": float(recent["reverse_identity_error"]),
        "baseline_reverse_identity_tolerance": float(baseline["reverse_identity_tolerance"]),
        "recent_reverse_identity_tolerance": float(recent["reverse_identity_tolerance"]),
        "baseline_reverse_scale_error": float(baseline["reverse_scale_error"]),
        "recent_reverse_scale_error": float(recent["reverse_scale_error"]),
        "baseline_reverse_scale_tolerance": float(baseline["reverse_scale_tolerance"]),
        "recent_reverse_scale_tolerance": float(recent["reverse_scale_tolerance"]),
        "baseline_reverse_identity_passed": bool(baseline["reverse_identity_passed"]),
        "recent_reverse_identity_passed": bool(recent["reverse_identity_passed"]),
        "baseline_first_response_index": int(baseline_indices[0]),
        "baseline_last_response_index": int(baseline_indices[-1]),
        "recent_first_response_index": int(recent_indices[0]),
        "recent_last_response_index": int(recent_indices[-1]),
        "baseline_first_antecedent_index": int(baseline_indices[0] - 1),
        "recent_first_antecedent_index": int(recent_indices[0] - 1),
    }''',
    )

    text = replace_section(
        text,
        "def feature_projection(",
        "def analyse(",
        '''def feature_projection(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = (
        "decision_index",
        "baseline_first_response_index",
        "baseline_last_response_index",
        "recent_first_response_index",
        "recent_last_response_index",
        "baseline_first_antecedent_index",
        "recent_first_antecedent_index",
        "baseline_asymmetry",
        "recent_asymmetry",
        "time_reversal_asymmetry_shift",
        "baseline_scale",
        "recent_scale",
        "baseline_reverse_value",
        "recent_reverse_value",
        "baseline_reverse_identity_error",
        "recent_reverse_identity_error",
        "baseline_reverse_identity_tolerance",
        "recent_reverse_identity_tolerance",
        "baseline_reverse_scale_error",
        "recent_reverse_scale_error",
        "baseline_reverse_scale_tolerance",
        "recent_reverse_scale_tolerance",
        "baseline_reverse_identity_passed",
        "recent_reverse_identity_passed",
    )
    return [{key: record[key] for key in keys} for record in records]


def return_pair_projection(returns: np.ndarray, records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "completed_training_returns": [float(value) for value in returns[1:]],
        "windows": [
            {
                "decision_index": int(record["decision_index"]),
                "baseline": [
                    int(record["baseline_first_response_index"]),
                    int(record["baseline_last_response_index"]),
                ],
                "recent": [
                    int(record["recent_first_response_index"]),
                    int(record["recent_last_response_index"]),
                ],
            }
            for record in records
        ],
    }


def delayed_label_projection(records: list[dict[str, Any]]) -> list[dict[str, float | int]]:
    return [
        {
            "decision_index": int(record["decision_index"]),
            "delayed_net_24h": float(record["delayed_net_24h"]),
            "delayed_adverse_24h": float(record["delayed_adverse_24h"]),
        }
        for record in records
    ]


def scalar_distribution(values: np.ndarray) -> dict[str, float]:
    return {
        "minimum": float(values.min()),
        "q25": float(np.quantile(values, 0.25)),
        "median": float(np.quantile(values, 0.5)),
        "q75": float(np.quantile(values, 0.75)),
        "maximum": float(values.max()),
    }''',
    )

    replacements = (
        (
            "causal-own-price-leverage-effect-relaxation-opportunity-1h-v1",
            "causal-own-price-time-reversal-asymmetry-shift-opportunity-1h-v1",
        ),
        (
            "accept_causal_own_price_leverage_effect_relaxation_information_premise_1h_v1",
            "accept_causal_own_price_time_reversal_asymmetry_shift_information_premise_1h_v1",
        ),
        (
            "reject_causal_own_price_leverage_effect_relaxation_information_premise_1h_v1",
            "reject_causal_own_price_time_reversal_asymmetry_shift_information_premise_1h_v1",
        ),
        ("SEED = 2026080223", "SEED = 2026080301"),
        ("feature = leverage_feature(returns, t)", "feature = asymmetry_feature(returns, t)"),
        ("leverage_relaxation", "time_reversal_asymmetry_shift"),
        (
            "# Own-price leverage-effect relaxation opportunity diagnostic",
            "# Own-price time-reversal-asymmetry shift opportunity diagnostic",
        ),
        (
            "Bilateral leverage-effect relaxation support failed: ",
            "Bilateral time-reversal-asymmetry shift support failed: ",
        ),
        ('"pair": "(r[i-1], r[i]^2)"', '"pair": "adjacent ordered returns (r[i-1],r[i])"'),
        (
            '"leverage_statistic": "-corr(r[i-1],r[i]^2)"',
            '"time_reversal_asymmetry_statistic": "mean(r_prev*r_now*(r_now-r_prev))/symmetric_rms^3"',
        ),
        (
            '"feature": "baseline_leverage-recent_leverage"',
            '"feature": "recent_asymmetry-baseline_asymmetry"',
        ),
    )
    for old, new in replacements:
        if old not in text:
            raise RuntimeError(f"required source fragment missing: {old!r}")
        text = text.replace(old, new)

    hash_block_old = '''    event_hash = base.sha256_bytes(base.canonical_bytes(records))
    prefix_event_hash = base.sha256_bytes(base.canonical_bytes(prefix_records))
    feature_hash = base.sha256_bytes(base.canonical_bytes(feature_projection(records)))
    prefix_feature_hash = base.sha256_bytes(base.canonical_bytes(feature_projection(prefix_records)))
    source_prefix_hash = base.sha256_bytes(base.canonical_bytes(source_prefix_projection(series, TRAIN_END)))
    truncated_source_prefix_hash = base.sha256_bytes(base.canonical_bytes(source_prefix_projection(prefix_series, TRAIN_END)))'''
    hash_block_new = '''    full_training_returns = completed_log_returns(series, TRAIN_END)
    prefix_training_returns = completed_log_returns(prefix_series, TRAIN_END)
    event_hash = base.sha256_bytes(base.canonical_bytes(records))
    prefix_event_hash = base.sha256_bytes(base.canonical_bytes(prefix_records))
    feature_hash = base.sha256_bytes(base.canonical_bytes(feature_projection(records)))
    prefix_feature_hash = base.sha256_bytes(base.canonical_bytes(feature_projection(prefix_records)))
    return_pair_hash = base.sha256_bytes(
        base.canonical_bytes(return_pair_projection(full_training_returns, records))
    )
    prefix_return_pair_hash = base.sha256_bytes(
        base.canonical_bytes(return_pair_projection(prefix_training_returns, prefix_records))
    )
    delayed_label_hash = base.sha256_bytes(base.canonical_bytes(delayed_label_projection(records)))
    prefix_delayed_label_hash = base.sha256_bytes(
        base.canonical_bytes(delayed_label_projection(prefix_records))
    )
    source_prefix_hash = base.sha256_bytes(base.canonical_bytes(source_prefix_projection(series, TRAIN_END)))
    truncated_source_prefix_hash = base.sha256_bytes(
        base.canonical_bytes(source_prefix_projection(prefix_series, TRAIN_END))
    )'''
    text = replace_once(text, hash_block_old, hash_block_new)

    distribution_marker = '''    associations = summary_stats(x, net, adverse)'''
    distribution_insert = '''    baseline_scales = np.array([record["baseline_scale"] for record in records], dtype=float)
    recent_scales = np.array([record["recent_scale"] for record in records], dtype=float)
    baseline_reverse_errors = np.array(
        [record["baseline_reverse_identity_error"] for record in records], dtype=float
    )
    recent_reverse_errors = np.array(
        [record["recent_reverse_identity_error"] for record in records], dtype=float
    )
    asymmetry_audit = {
        "baseline_scale_distribution": scalar_distribution(baseline_scales),
        "recent_scale_distribution": scalar_distribution(recent_scales),
        "maximum_baseline_reverse_identity_error": float(baseline_reverse_errors.max()),
        "maximum_recent_reverse_identity_error": float(recent_reverse_errors.max()),
        "maximum_reverse_identity_error": float(
            max(baseline_reverse_errors.max(), recent_reverse_errors.max())
        ),
        "all_scales_finite_and_positive": bool(
            np.isfinite(baseline_scales).all()
            and np.isfinite(recent_scales).all()
            and np.all(baseline_scales > 0)
            and np.all(recent_scales > 0)
        ),
        "all_reverse_identity_passed": all(
            record["baseline_reverse_identity_passed"]
            and record["recent_reverse_identity_passed"]
            and record["baseline_reverse_identity_error"]
            <= record["baseline_reverse_identity_tolerance"]
            and record["recent_reverse_identity_error"]
            <= record["recent_reverse_identity_tolerance"]
            and record["baseline_reverse_scale_error"]
            <= record["baseline_reverse_scale_tolerance"]
            and record["recent_reverse_scale_error"]
            <= record["recent_reverse_scale_tolerance"]
            for record in records
        ),
        "windows_checked": 2 * len(records),
    }
    associations = summary_stats(x, net, adverse)'''
    text = replace_once(text, distribution_marker, distribution_insert)

    gate_marker = '''        "no_invalid_feature_anchors": grid_audit["invalid_feature_anchors"] == 0,
        "exact_frozen_pair_windows": all('''
    gate_insert = '''        "no_invalid_feature_anchors": grid_audit["invalid_feature_anchors"] == 0,
        "finite_positive_symmetric_rms_scales": asymmetry_audit["all_scales_finite_and_positive"],
        "reverse_order_antisymmetry_identity": asymmetry_audit["all_reverse_identity_passed"],
        "exact_frozen_pair_windows": all('''
    text = replace_once(text, gate_marker, gate_insert)

    prefix_gate_marker = '''        "source_prefix_invariant": source_prefix_hash == truncated_source_prefix_hash,
        "feature_prefix_invariant": feature_hash == prefix_feature_hash,
        "opportunity_prefix_invariant": event_hash == prefix_event_hash,'''
    prefix_gate_insert = '''        "source_prefix_invariant": source_prefix_hash == truncated_source_prefix_hash,
        "return_pair_prefix_invariant": return_pair_hash == prefix_return_pair_hash,
        "feature_prefix_invariant": feature_hash == prefix_feature_hash,
        "opportunity_prefix_invariant": event_hash == prefix_event_hash,
        "delayed_label_prefix_invariant": delayed_label_hash == prefix_delayed_label_hash,'''
    text = replace_once(text, prefix_gate_marker, prefix_gate_insert)

    return_marker = '''        "distribution": distribution,
        "associations": associations,'''
    return_insert = '''        "distribution": distribution,
        "asymmetry_audit": asymmetry_audit,
        "associations": associations,'''
    text = replace_once(text, return_marker, return_insert)

    hash_return_marker = '''        "feature_sha256": feature_hash,
        "prefix_feature_sha256": prefix_feature_hash,
        "gates": gates,'''
    hash_return_insert = '''        "feature_sha256": feature_hash,
        "prefix_feature_sha256": prefix_feature_hash,
        "return_pair_sha256": return_pair_hash,
        "prefix_return_pair_sha256": prefix_return_pair_hash,
        "delayed_label_sha256": delayed_label_hash,
        "prefix_delayed_label_sha256": prefix_delayed_label_hash,
        "gates": gates,'''
    text = replace_once(text, hash_return_marker, hash_return_insert)

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

    required = (
        "def asymmetry_statistic(",
        "def asymmetry_feature(",
        'feature = float(recent["value"] - baseline["value"])',
        'record["time_reversal_asymmetry_shift"]',
        '"reverse_order_antisymmetry_identity"',
        '"return_pair_prefix_invariant"',
        '"delayed_label_prefix_invariant"',
        '"time_reversal_asymmetry_statistic":',
        '"feature": "recent_asymmetry-baseline_asymmetry"',
    )
    missing = [fragment for fragment in required if fragment not in text]
    if missing:
        raise RuntimeError(f"transformed diagnostic is missing required bindings: {missing}")
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
