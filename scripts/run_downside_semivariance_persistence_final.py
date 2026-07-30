# ruff: noqa
# fmt: off
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

METRIC_FIELDS = [
    "net_return", "sharpe", "max_drawdown", "turnover", "fees",
    "edge_per_turnover_bps", "mean_exposure", "half_exposure_hours",
    "full_exposure_hours",
]

FAILURE_SECTION = """## Failure mechanism

The same fixed downside-asymmetry state had opposite economics across the two development markets.

- **BTC:** the candidate reduced B1 exposure by 2,952 full-exposure-equivalent hours. Risk-trigger decisions were followed by positive mean market returns over both 24H and 168H horizons, so the half-risk state removed **5.83%** of arithmetic market return and added **0.35%** of incremental fees. OOS return remained below B1, turnover rose from 45 to 52, edge per turnover fell from 212.75 to 172.23 bps, residual Sharpe was negative, and only 4/12 folds improved versus B1.
- **ETH:** the half-risk state avoided approximately **1.23%** of arithmetic market loss and materially improved OOS return, Sharpe and drawdown. However, turnover rose from 30 to 34, edge per turnover fell from 283.58 to 253.24 bps, only 5/12 folds improved versus B1, and both paired moving-block lower confidence bounds remained negative.

The feature frequency was stable rather than disappearing: trigger rates moved from 30.98% to 26.67% for BTC and from 31.15% to 29.81% for ETH. The rejection is therefore economic and cross-market, not a feature-activation failure. A fixed downside-energy state did not transport reliably enough to support bilateral qualification.

## Repaired discrepancy

The first diagnostic version attributed turnover transitions using the decision-bar index, while fees are incurred at the following next-open execution bar. Transition attribution was repaired to use the stored execution index `t+1`, and exact turnover reconstruction was asserted against the backtest ledger. The complete experiment was rerun twice with byte-identical protocol, result and report outputs. No signal, exposure, fee, metric, bootstrap result, acceptance gate or verdict changed.

"""


def compact(full: dict) -> dict:
    out = {k: full[k] for k in [
        "issue", "family_id", "candidate_count", "parameter_grid_count",
        "accepted", "verdict", "repaired_discrepancy", "remaining_blocker",
        "next_experiment",
    ]}
    out["sample"] = {
        "training": [2880, 17520],
        "development_oos": [17520, 43440],
        "full_scored": [2880, 43440],
        "folds": 12,
        "fold_hours": 2160,
        "later_suffix_unread": True,
        "fee_one_way": 0.0005,
    }
    out["markets"] = {}
    for market, value in full["markets"].items():
        diagnostics = value["diagnostics"]
        decomposition = diagnostics["oos_exposure_decomposition"]
        features = diagnostics["features"]
        out["markets"][market] = {
            "source": value["source"],
            "metrics": {
                sample: {
                    policy: {
                        key: value["metrics"][sample][policy][key]
                        for key in METRIC_FIELDS
                    }
                    for policy in ["candidate", "b1"]
                }
                for sample in ["training", "development_oos", "full_scored"]
            },
            "b0_development_oos": {
                key: value["metrics"]["development_oos"]["b0"][key]
                for key in METRIC_FIELDS
            },
            "breadth": {
                key: value["breadth"][key]
                for key in [
                    "profitable_folds", "profitable_years",
                    "positive_fold_concentration",
                ]
            },
            "uncertainty": value["uncertainty"],
            "residual_sharpe": value["residual_sharpe"],
            "acceptance": value["acceptance"],
            "diagnostics": {
                "training_trigger_rate": features["training"]["risk_trigger_rate"],
                "oos_trigger_rate": features["development_oos"]["risk_trigger_rate"],
                "candidate_less_exposure_hours": decomposition["candidate_less_exposure_hours"],
                "exposure_delta_market_arithmetic_return": decomposition["exposure_delta_market_arithmetic_return"],
                "incremental_fees_candidate_minus_b1": decomposition["incremental_fees_candidate_minus_b1"],
                "observed_candidate_minus_b1_arithmetic_net": decomposition["observed_candidate_minus_b1_arithmetic_net"],
                "decomposition_identity_passes": decomposition["identity_passes"],
                "improved_arithmetic_net_folds_vs_b1": diagnostics["improved_arithmetic_net_folds_vs_b1"],
                "oos_forward_risk_trigger": diagnostics["forward_diagnostics"]["development_oos"]["risk_trigger"],
                "oos_transition_turnover": diagnostics["oos_transitions"]["total_decision_turnover"],
            },
        }
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--btc", type=Path, required=True)
    parser.add_argument("--eth", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    runner = Path(__file__).with_name("run_downside_semivariance_persistence.py")
    with tempfile.TemporaryDirectory() as temp:
        temp_path = Path(temp)
        subprocess.run(
            [sys.executable, str(runner), "--btc", str(args.btc), "--eth", str(args.eth), "--output-dir", str(temp_path)],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        full = json.loads((temp_path / "result.json").read_text())
        result = compact(full)
        report = (temp_path / "report.md").read_text()
        report = report.replace("## Verdict\n", FAILURE_SECTION + "## Verdict\n")
        (args.output_dir / "protocol.json").write_bytes((temp_path / "protocol.json").read_bytes())
        (args.output_dir / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        (args.output_dir / "report.md").write_text(report)
    print(json.dumps({"accepted": result["accepted"], "verdict": result["verdict"]}, sort_keys=True))


if __name__ == "__main__":
    main()
