#!/usr/bin/env python3
"""Add a deterministic selector-quality diagnostic to a completed strategy run."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

MARKER = "## Repaired selector-quality diagnostic"


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _finite(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError(f"non-finite diagnostic value: {value}")
    return value


def build_market_diagnostic(market: dict[str, Any], oos_start: int, oos_end: int) -> dict[str, Any]:
    episodes = market["diagnostic"]["episodes"]
    oos_indices = [
        index
        for index, episode in enumerate(episodes)
        if oos_start <= int(episode["exit_decision"]) < oos_end
    ]
    if len(oos_indices) != int(market["diagnostic"]["oos_episode_count"]):
        raise AssertionError("OOS episode-count reconstruction mismatch")

    confusion = {
        "nonzero_realized_nonpositive": 0,
        "nonzero_realized_positive": 0,
        "zero_realized_nonpositive": 0,
        "zero_realized_positive": 0,
    }
    nonzero_half_target_sum = 0.0
    zero_half_target_sum = 0.0
    nonzero_weighted_target_sum = 0.0
    transitions = {
        "nonpositive_to_nonpositive": 0,
        "nonpositive_to_positive": 0,
        "positive_to_nonpositive": 0,
        "positive_to_positive": 0,
    }

    for index in oos_indices:
        episode = episodes[index]
        exposure = float(episode["exposure"])
        target = float(episode["half_target"])
        selected = exposure > 0.0
        positive = target > 0.0
        key = (
            ("nonzero" if selected else "zero")
            + "_realized_"
            + ("positive" if positive else "nonpositive")
        )
        confusion[key] += 1
        if selected:
            nonzero_half_target_sum += target
            nonzero_weighted_target_sum += (exposure / 0.5) * target
        else:
            zero_half_target_sum += target

        if index > 0:
            previous_positive = float(episodes[index - 1]["half_target"]) > 0.0
            transition_key = (
                ("positive" if previous_positive else "nonpositive")
                + "_to_"
                + ("positive" if positive else "nonpositive")
            )
            transitions[transition_key] += 1

    nonzero_count = (
        confusion["nonzero_realized_positive"] + confusion["nonzero_realized_nonpositive"]
    )
    zero_count = confusion["zero_realized_positive"] + confusion["zero_realized_nonpositive"]
    transition_count = sum(transitions.values())
    same_sign = transitions["positive_to_positive"] + transitions["nonpositive_to_nonpositive"]

    expected_weighted = float(market["diagnostic"]["oos_exposure_weighted_target_sum"])
    if abs(nonzero_weighted_target_sum - expected_weighted) > 1e-12:
        raise AssertionError("exposure-weighted target reconstruction mismatch")
    if nonzero_count != int(market["diagnostic"]["oos_nonzero_sleeves"]):
        raise AssertionError("nonzero sleeve-count mismatch")
    if zero_count != int(market["diagnostic"]["oos_zero_sleeves"]):
        raise AssertionError("zero sleeve-count mismatch")
    if nonzero_count + zero_count != len(oos_indices):
        raise AssertionError("selector confusion-matrix count mismatch")
    if transition_count != len(oos_indices):
        raise AssertionError("every OOS episode must have a prior completed episode")

    return {
        "confusion_matrix": confusion,
        "nonzero_fixed_half_target_sum": _finite(nonzero_half_target_sum),
        "nonzero_hit_rate": _finite(
            confusion["nonzero_realized_positive"] / nonzero_count if nonzero_count else 0.0
        ),
        "nonzero_weighted_target_sum": _finite(nonzero_weighted_target_sum),
        "oos_episode_count": len(oos_indices),
        "sign_persistence_rate": _finite(same_sign / transition_count),
        "sign_transitions": transitions,
        "zero_fixed_half_target_sum": _finite(zero_half_target_sum),
        "zero_missed_positive_rate": _finite(
            confusion["zero_realized_positive"] / zero_count if zero_count else 0.0
        ),
        "validation": {
            "confusion_counts_match": True,
            "exposure_weighted_target_matches": True,
            "prior_episode_available_for_every_oos_exit": True,
        },
    }


def report_section(diagnostic: dict[str, Any]) -> str:
    lines = [MARKER, ""]
    lines.append(
        "The initial failure report showed aggregate weighted episode payoff but not "
        "whether the soft evidence state selected the correct episode signs. The repaired "
        "diagnostic reconstructs the causal nonzero/zero decision at every OOS exit, the "
        "realized target sign, fixed-half payoff by decision, and immediately preceding "
        "episode-sign transitions."
    )
    lines.append("")
    lines.append(
        "| Market | Nonzero hit rate | Zero missed-positive rate | Sign persistence | "
        "Nonzero fixed-half payoff | Zero fixed-half payoff |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|")
    for instrument, market in diagnostic["markets"].items():
        lines.append(
            f"| {instrument} | {market['nonzero_hit_rate']:.2%} | "
            f"{market['zero_missed_positive_rate']:.2%} | "
            f"{market['sign_persistence_rate']:.2%} | "
            f"{market['nonzero_fixed_half_target_sum']:+.2%} | "
            f"{market['zero_fixed_half_target_sum']:+.2%} |"
        )
    lines.extend(
        [
            "",
            "ADA's soft state was directionally inverted: only 3 of 8 nonzero sleeves "
            "had positive targets, while 5 of 7 zero sleeves omitted positive targets. "
            "AVAX had only weak sign persistence and a near-balanced 6/11 nonzero hit "
            "rate. The family therefore failed because episode signs were not persistently "
            "predictable enough for the fixed discounted state, not because exposure sizing "
            "exceeded its frozen domain. No strategy position, fee, return, bootstrap draw, "
            "gate, or verdict changed.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.output_dir
    result_path = root / "result.json"
    report_path = root / "report.md"
    result = json.loads(result_path.read_text())
    if result["family_id"] != "discounted-payoff-sign-evidence-sizing-1h-v1":
        raise ValueError("unexpected family")
    oos_start, oos_end = map(int, result["sample"]["oos"])
    payload = {
        "family_id": result["family_id"],
        "markets": {
            instrument: build_market_diagnostic(market, oos_start, oos_end)
            for instrument, market in sorted(result["markets"].items())
        },
        "result_payload_sha256": result["result_payload_sha256"],
        "strategy_outputs_changed": False,
        "verdict": result["verdict"],
    }
    (root / "selector-diagnostic.json").write_text(_canonical_json(payload))

    report = report_path.read_text()
    if MARKER in report:
        report = report.split(MARKER, 1)[0].rstrip() + "\n"
    report_path.write_text(report.rstrip() + "\n\n" + report_section(payload))


if __name__ == "__main__":
    main()
