from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

INITIAL_SHA256 = "d92b9626a9429c2177f292ddef7555dbf4b2f3c713ccf120ef4708906c7c49c3"
REPAIRED_SHA256 = "e279e1f24f5c90bea154833918874ec4ed33e5ed1635413fa98d7d25f652dd0b"

OLD = """    checks = {
        "deterministic_filter_weight_and_signal_replay": deterministic,
        "proper_score_weights_finite_positive_and_normalised": weight_valid,
        "daily_only_target_changes": bool(daily_only),
        "next_open_and_exact_fee_paths": bool(exact_paths),
        "segment_cash_reset_and_terminal_liquidation": bool(segment_reset),
        "source_endpoint_excludes_unscored_suffix": bool(OOS_END + 1 <= SOURCE_END),
"""

NEW = """    truncated = MarketData(
        symbol=data.symbol,
        timestamp_ms=data.timestamp_ms[: OOS_END + 1].copy(),
        open=data.open[: OOS_END + 1].copy(),
        high=data.high[: OOS_END + 1].copy(),
        low=data.low[: OOS_END + 1].copy(),
        close=data.close[: OOS_END + 1].copy(),
        volume=data.volume[: OOS_END + 1].copy(),
        manifest=data.manifest,
        canonical_sha256=data.canonical_sha256,
    )
    truncated_forecasts = local_linear_forecasts(truncated)
    truncated_fit = training_weights(truncated, truncated_forecasts)
    truncated_weighted = truncated_forecasts @ truncated_fit["weights"]
    truncated_equal = truncated_forecasts @ np.full(3, 1.0 / 3.0)
    suffix_invariant = bool(
        np.array_equal(forecasts[: OOS_END + 1], truncated_forecasts)
        and np.array_equal(fit["weights"], truncated_fit["weights"])
        and np.array_equal(weighted[: OOS_END + 1], truncated_weighted)
        and np.array_equal(equal[: OOS_END + 1], truncated_equal)
    )
    for segment_name, (segment_start, segment_end) in {
        "train": (TRAIN_START, TRAIN_END),
        "oos": (TRAIN_END, OOS_END),
        "full": (TRAIN_START, OOS_END),
    }.items():
        suffix_invariant = suffix_invariant and np.array_equal(
            raw[segment_name]["candidate"]["positions"],
            build_hysteretic_positions(truncated, truncated_weighted, segment_start, segment_end),
        )
        suffix_invariant = suffix_invariant and np.array_equal(
            raw[segment_name]["equal_weight"]["positions"],
            build_hysteretic_positions(truncated, truncated_equal, segment_start, segment_end),
        )
        suffix_invariant = suffix_invariant and np.array_equal(
            raw[segment_name]["trend"]["positions"],
            build_daily_trend_positions(truncated, segment_start, segment_end),
        )

    checks = {
        "deterministic_filter_weight_and_signal_replay": deterministic,
        "proper_score_weights_finite_positive_and_normalised": weight_valid,
        "daily_only_target_changes": bool(daily_only),
        "next_open_and_exact_fee_paths": bool(exact_paths),
        "segment_cash_reset_and_terminal_liquidation": bool(segment_reset),
        "unscored_suffix_truncation_invariance": bool(suffix_invariant),
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    return parser.parse_args()


def main() -> None:
    path = parse_args().path
    original = path.read_bytes()
    initial = hashlib.sha256(original).hexdigest()
    if initial != INITIAL_SHA256:
        raise RuntimeError(f"unexpected initial source SHA-256: {initial}")
    text = original.decode("utf-8")
    if text.count(OLD) != 1:
        raise RuntimeError("suffix-audit patch anchor is not unique")
    repaired = text.replace(OLD, NEW).encode("utf-8")
    digest = hashlib.sha256(repaired).hexdigest()
    if digest != REPAIRED_SHA256:
        raise RuntimeError(f"unexpected repaired source SHA-256: {digest}")
    path.write_bytes(repaired)


if __name__ == "__main__":
    main()
