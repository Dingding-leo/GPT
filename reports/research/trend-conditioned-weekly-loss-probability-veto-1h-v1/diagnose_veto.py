#!/usr/bin/env python3
"""Diagnose effective veto calibration and blocked B1 exposure episodes."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np


def load_experiment(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("trend_loss_veto_experiment", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load experiment module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical_bytes(value: Any) -> bytes:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return (text + "\n").encode()


def label_group(mask: np.ndarray, labels: np.ndarray, hurdle: float) -> dict[str, Any]:
    values = labels[mask]
    return {
        "count": int(len(values)),
        "mean": float(np.mean(values)) if len(values) else None,
        "sum": float(np.sum(values)),
        "positive_fraction": float(np.mean(values > 0)) if len(values) else None,
        "fee_hurdle_success_fraction": (
            float(np.mean(values > hurdle)) if len(values) else None
        ),
    }


def contiguous_episodes(mask: np.ndarray) -> list[tuple[int, int]]:
    indices = np.flatnonzero(mask)
    if not len(indices):
        return []
    starts = [int(indices[0])]
    ends: list[int] = []
    for previous, current in zip(indices[:-1], indices[1:], strict=True):
        if current != previous + 1:
            ends.append(int(previous + 1))
            starts.append(int(current))
    ends.append(int(indices[-1] + 1))
    return list(zip(starts, ends, strict=True))


def diagnose_market(module: ModuleType, data_root: Path, instrument: str) -> dict[str, Any]:
    market = module.load_market(module.find_csv(data_root, instrument), instrument)
    built = module.build_paths(market)
    start, end = module.OOS
    index = np.arange(len(built["decision_mask"]))
    valid = (
        built["decision_mask"]
        & (index >= start)
        & (index < end)
        & np.isfinite(built["probability_lower"])
        & np.isfinite(built["realized_label"])
    )
    base = np.zeros(len(market["closes"]), dtype=np.int8)
    base[2_160:] = (market["closes"][2_160:] > market["closes"][:-2_160]).astype(
        np.int8
    )
    effective = valid & (base == 1)
    vetoed = effective & (built["probability_lower"] > 0.5)
    allowed = effective & ~vetoed

    candidate = built["paths"]["candidate"]
    benchmark = built["paths"]["B1"]
    candidate_position = candidate["position"][start:end]
    benchmark_position = benchmark["position"][start:end]
    blocked = (candidate_position == 0) & (benchmark_position == 1)
    return_timestamps = market["timestamps"].iloc[1:].reset_index(drop=True)
    episodes = []
    for local_start, local_end in contiguous_episodes(blocked):
        absolute_start = start + local_start
        absolute_end = start + local_end
        gross = float(np.sum(benchmark["gross"][absolute_start:absolute_end]))
        episodes.append(
            {
                "start": return_timestamps.iloc[absolute_start].isoformat(),
                "end_exclusive": return_timestamps.iloc[absolute_end].isoformat(),
                "hours": int(local_end - local_start),
                "B1_gross_return_sum": gross,
                "candidate_minus_B1_gross": -gross,
            }
        )
    missed_gains = [episode for episode in episodes if episode["B1_gross_return_sum"] > 0]
    avoided_losses = [episode for episode in episodes if episode["B1_gross_return_sum"] < 0]
    return {
        "instrument": instrument,
        "effective_weekly_decisions": int(np.sum(effective)),
        "effective_veto_frequency": (
            float(np.mean(vetoed[effective])) if np.any(effective) else 0.0
        ),
        "effective_vetoed_labels": label_group(
            vetoed, built["realized_label"], module.HURDLE
        ),
        "effective_allowed_labels": label_group(
            allowed, built["realized_label"], module.HURDLE
        ),
        "blocked_B1_hours": int(np.sum(blocked)),
        "blocked_episode_count": len(episodes),
        "missed_gain_episode_count": len(missed_gains),
        "avoided_loss_episode_count": len(avoided_losses),
        "missed_gain_sum": float(
            sum(episode["B1_gross_return_sum"] for episode in missed_gains)
        ),
        "avoided_loss_sum": float(
            sum(-episode["B1_gross_return_sum"] for episode in avoided_losses)
        ),
        "net_gross_value_of_veto": float(
            -sum(episode["B1_gross_return_sum"] for episode in episodes)
        ),
        "largest_missed_gains": sorted(
            missed_gains,
            key=lambda episode: episode["B1_gross_return_sum"],
            reverse=True,
        )[:5],
        "largest_avoided_losses": sorted(
            avoided_losses,
            key=lambda episode: episode["B1_gross_return_sum"],
        )[:5],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--instrument", action="append", required=True)
    args = parser.parse_args()
    if len(args.instrument) != 2 or len(set(args.instrument)) != 2:
        raise ValueError("exactly two distinct instruments are required")
    module = load_experiment(args.runner)
    result = {
        "schema_version": 1,
        "family_id": "trend-conditioned-weekly-loss-probability-veto-1h-v1",
        "diagnostic_scope": (
            "OOS effective positive-trend vetoes and contiguous B1-only episodes"
        ),
        "strategy_outputs_changed": False,
        "markets": [
            diagnose_market(module, args.data_root, instrument)
            for instrument in args.instrument
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_bytes(result))


if __name__ == "__main__":
    main()
