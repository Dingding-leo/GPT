from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

FAMILY_ID = "causal-own-price-linear-supervised-selector-programme-closure-1h-v1"
VERDICT = "reject_reopening_completed_fixed_linear_supervised_selector_mechanisms_1h_v1"
CANONICAL_MAIN = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
FEE_BPS_ONE_WAY = 5.0

PRIOR_CLOSURE: dict[str, Any] = {
    "issue": 1022,
    "pr": 1023,
    "family_id": "causal-own-history-label-trained-selector-programme-closure-1h-v1",
    "exact_head": "e00f8159450e7cb834648dcc8053eae3167714f4",
    "workflow": 30784027407,
    "artifact": 8844620659,
    "artifact_zip_sha256": "48c8823edda65c88cf760ef6d97eaeaf1a64e7337b02581b65991eaba352dc1d",
    "evidence_sha256": "50fbe1ece70c01e9a4f94dc79ae16a5129b40796f806a782d0de1f1d88683d61",
    "report_sha256": "d8ce155dff5828396289e42e5ef4bfa952d6fec6add8382fff04100ee33498b9",
    "source_records_sha256": "cbe949e4dbd340378d545029098739ce449470386a14282093b5967d0d02c331",
    "bound_groups": 8,
    "fully_supportive_groups": 0,
    "closure_gates_passed": 1,
    "closure_gates_total": 12,
    "new_rows": 0,
    "new_labels": 0,
    "new_oos": 0,
    "verdict": "reject_reopening_completed_own_history_label_trained_selector_mechanisms_1h_v1",
    "group_records": [
        {
            "group": "direct_forecasting",
            "targets": {
                "UNI-USDT": {
                    "oos_net_return": -0.7600,
                    "oos_sharpe": -0.466,
                    "full_net_return": -0.6380,
                },
                "AAVE-USDT": {
                    "oos_net_return": -0.2120,
                    "full_net_return": -0.2588,
                },
            },
            "supportive": False,
        },
        {
            "group": "empirical_downside_bounds",
            "targets": ["ETC-USDT", "COMP-USDT"],
            "active_oos_weeks": 0,
            "eligible_oos_weeks": 154,
            "sharpe": None,
            "edge_per_turnover": None,
            "supportive": False,
        },
        {
            "group": "loss_probability_veto",
            "targets": {
                "NEAR-USDT": {
                    "oos_net_return": 1.1330,
                    "oos_b1_net_return": 3.5998,
                },
                "SAND-USDT": {
                    "oos_net_return": 0.2894,
                    "full_net_return": -0.1965,
                    "positive_fold_concentration": 0.7973,
                },
            },
            "supportive": False,
        },
        {
            "group": "payoff_sizing",
            "targets": {
                "KSM-USDT": {"oos_net_return": -0.1120},
                "IOTA-USDT": {
                    "oos_net_return": 0.1968,
                    "full_net_return": -0.1810,
                },
            },
            "common_annualized_mean_delta": -0.1834,
            "common_annualized_mean_delta_ci95": [-0.5553, 0.1628],
            "supportive": False,
        },
        {
            "group": "haar_classifier",
            "training_net_return_floor": 1.27,
            "oos_net_returns": [-0.5899, -0.6588],
            "turnover_multiple_vs_e2160": 10.3,
            "supportive": False,
        },
        {
            "group": "historical_analog",
            "targets": {
                "ATOM-USDT": {
                    "oos_net_return": 0.6122,
                    "oos_sharpe": 1.392,
                    "delayed_oos_net_return": -0.0514,
                },
                "ALGO-USDT": {"underperformed_e2160": True},
            },
            "supportive": False,
        },
        {
            "group": "bocpd_entry",
            "targets": {
                "LINK-USDT": {
                    "oos_net_return": 0.4174,
                    "full_net_return": 0.7891,
                    "profitable_folds": 2,
                    "fold_count": 6,
                    "mean_delta_lower_bound": -0.00000389,
                },
                "COMP-USDT": {"negative_economics": True},
            },
            "supportive": False,
        },
        {
            "group": "conformal_selector",
            "targets": {
                "BCH-USDT": {"fit_positive_count": 39, "fit_count": 330},
                "LINK-USDT": {"fit_positive_count": 62, "fit_count": 330},
            },
            "minimum_fit_positive_count": 80,
            "labels": None,
            "economics": None,
            "supportive": False,
        },
    ],
}

RIDGE_EXCEPTION: dict[str, Any] = {
    "issue": 1055,
    "pr": 1059,
    "family_id": "causal-own-price-ridge-lag-strip-utility-selector-1h-v1",
    "exact_head": "d3727ee60f48c8266e68d2d414f7e03b45b9c7c7",
    "workflow": 30819390397,
    "artifact": 8858418482,
    "artifact_zip_sha256": "e3912e08e87f3637967251ba46a8d5c2d160f091080cd7f8dce868d0f0295253",
    "evidence_sha256": "071209addf9012616313f825cb56039d1b195c9345f6420e15935577bed70c69",
    "report_sha256": "b5145e2cf941e9dc44bfa22f688bbaa843ce08f710070ec1df9b3757c64dabe1",
    "candidate_count": 1,
    "parameter_grid_count": 0,
    "bilateral_validation_pass": False,
    "sealed_oos_accessed": False,
    "verdict": "reject_causal_own_price_ridge_lag_strip_utility_selector_1h_v1",
    "targets": {
        "ETC-USDT": {
            "source_rows": 24144,
            "source_sha256": "7d607aa0a3f86981f0f71907a0d28d66a77888eeb751a9566609390932a58e7f",
            "fit_support": 88,
            "fit_support_required": 100,
            "validation_support": 122,
            "validation_active": 62,
            "validation_active_fraction": 0.5082,
            "beta_norm": 0.033521,
            "gram_condition": 7.8662,
            "model_hash": "6a6e470eaa8f508214dd9476b6217dd86ac85d9180a01dbafc2c1c35069b8e69",
            "fit_candidate_net_return": 1.5913,
            "fit_candidate_sharpe": 4.190,
            "fit_max_drawdown": -0.0851,
            "fit_turnover": 42.0,
            "validation_candidate_gross_return": -0.1168,
            "validation_candidate_net_return": -0.1429,
            "validation_candidate_sharpe": -0.287,
            "validation_candidate_max_drawdown": -0.3808,
            "validation_candidate_turnover": 60.0,
            "validation_candidate_edge_per_turnover_bps": -23.82,
            "validation_e2160_net_return": 0.3371,
            "validation_e2160_sharpe": 1.267,
            "validation_e2160_turnover": 10.0,
            "validation_always_long_net_return": -0.0268,
            "validation_always_long_sharpe": 0.368,
            "oos": None,
            "full": None,
            "breadth": None,
            "uncertainty": None,
            "execution_delay": None,
        },
        "FIL-USDT": {
            "source_rows": 24144,
            "source_sha256": "09eed7b11e76222f54e8d381f069ddb176e91035143aa83edbd44f3ca5b0b55f",
            "fit_support": 78,
            "fit_support_required": 100,
            "validation_support": 110,
            "validation_active": 68,
            "validation_active_fraction": 0.6182,
            "beta_norm": 0.030048,
            "gram_condition": 6.2244,
            "model_hash": "2929ecb10dfd1f565338cc1cf17698a3a69c2e88124519e13909ea5abcc6632b",
            "fit_candidate_net_return": 1.2560,
            "fit_candidate_sharpe": 3.561,
            "fit_max_drawdown": -0.1828,
            "fit_turnover": 40.0,
            "validation_candidate_gross_return": -0.0228,
            "validation_candidate_net_return": -0.0489,
            "validation_candidate_sharpe": 0.249,
            "validation_candidate_max_drawdown": -0.4823,
            "validation_candidate_turnover": 54.0,
            "validation_candidate_edge_per_turnover_bps": -9.05,
            "validation_e2160_net_return": 0.1911,
            "validation_e2160_sharpe": 0.926,
            "validation_e2160_turnover": 4.0,
            "validation_always_long_net_return": -0.1370,
            "validation_always_long_sharpe": 0.200,
            "oos": None,
            "full": None,
            "breadth": None,
            "uncertainty": None,
            "execution_delay": None,
        },
    },
}


def canonical_json(value: Any) -> bytes:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (text + "\n").encode()


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def build_gates() -> dict[str, bool]:
    return {
        "bound_evidence_identities_reconcile": True,
        "ridge_passed_every_bilateral_validation_gate": False,
        "ridge_sufficient_fit_support_bilateral": False,
        "ridge_positive_validation_return_and_sharpe_bilateral": False,
        "ridge_authorised_oos": False,
        "ridge_positive_oos_full_and_benchmark_superiority": False,
        "ridge_preserved_turnover_and_improved_edge_per_turnover": False,
        "ridge_preserved_acceptable_drawdown": False,
        "ridge_passed_fold_year_breadth_and_concentration": False,
        "ridge_positive_dependence_lower_bounds": False,
        "ridge_passed_one_hour_delay": False,
        "leave_one_evidence_unit_out_support": False,
    }


def build_report(evidence: dict[str, Any]) -> str:
    ridge = evidence["ridge_exception"]["targets"]
    lines = [
        "# Fixed linear supervised selector programme closure 1H v1",
        "",
        f"`{evidence['verdict']}`",
        "",
        "## Incremental adjudication",
        "",
        "The prior eight-group label-trained selector closure had zero fully supportive groups. "
        "The separately preregistered ridge lag-strip exception also failed before OOS, so it "
        "does not change the family disposition.",
        "",
        (
            "| Target | Fit support | Fit net / Sharpe | Validation candidate | "
            "Validation E2160 | Turnover candidate / E2160 |"
        ),
        "|---|---:|---:|---:|---:|---:|",
    ]
    for target, result in ridge.items():
        lines.append(
            f"| {target} | {result['fit_support']}/{result['fit_support_required']} | "
            f"{100 * result['fit_candidate_net_return']:+.2f}% / "
            f"{result['fit_candidate_sharpe']:+.3f} | "
            f"{100 * result['validation_candidate_net_return']:+.2f}% / "
            f"{result['validation_candidate_sharpe']:+.3f} | "
            f"{100 * result['validation_e2160_net_return']:+.2f}% / "
            f"{result['validation_e2160_sharpe']:+.3f} | "
            f"{result['validation_candidate_turnover']:.0f} / "
            f"{result['validation_e2160_turnover']:.0f} |"
        )
    lines += [
        "",
        "Both ridge targets were under the frozen fit-support minimum. Both fit paths showed "
        "large apparent gains, then reversed to validation losses while suppressing profitable "
        "E2160 exposure and increasing turnover by 6.0x to 13.5x.",
        "",
        "The artifact also persists all eight original #1022 group scorecards without duplicate "
        "votes, recomputation or altered acceptance rules.",
        "",
        "OOS, full-period, fold/year breadth, dependence uncertainty and execution-delay fields "
        "remain null rather than zero because the bilateral validation gate failed.",
        "",
        "Leave-one-unit-out fails in both directions: removing the ridge exception leaves the "
        "already-rejected eight-group closure; removing the prior closure leaves a ridge "
        "exception that failed support and validation bilaterally. Removing either ETC or FIL "
        "also cannot create a bilateral pass.",
        "",
        "This closure accessed no market row, target label, fitted value, candidate path, "
        "benchmark path, bootstrap draw or sealed OOS observation.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tested-head", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    if len(args.tested_head) != 40:
        raise ValueError("tested head must be a 40-character commit SHA")
    gates = build_gates()
    if sum(gates.values()) != 1:
        raise AssertionError("closure gate vector changed")
    if len(PRIOR_CLOSURE["group_records"]) != PRIOR_CLOSURE["bound_groups"]:
        raise AssertionError("prior closure group matrix is incomplete")
    if any(group["supportive"] for group in PRIOR_CLOSURE["group_records"]):
        raise AssertionError("prior closure support disposition changed")
    targets = RIDGE_EXCEPTION["targets"]
    if set(targets) != {"ETC-USDT", "FIL-USDT"}:
        raise AssertionError("fixed target identity changed")
    if any(result["fit_support"] >= result["fit_support_required"] for result in targets.values()):
        raise AssertionError("frozen fit-support failure changed")
    if any(result["validation_candidate_net_return"] >= 0 for result in targets.values()):
        raise AssertionError("frozen validation loss identity changed")
    if any(result["oos"] is not None for result in targets.values()):
        raise AssertionError("sealed OOS must remain unread")

    evidence: dict[str, Any] = {
        "schema_version": 1,
        "family_id": FAMILY_ID,
        "verdict": VERDICT,
        "tested_head": args.tested_head,
        "canonical_main": CANONICAL_MAIN,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "new_market_rows": 0,
        "new_target_labels": 0,
        "new_oos_observations": 0,
        "canonical_fee_bps_one_way": FEE_BPS_ONE_WAY,
        "bound_evidence_units": 2,
        "independently_supportive_units": 0,
        "closure_gates": gates,
        "closure_gates_passed": 1,
        "closure_gates_total": 12,
        "prior_closure": PRIOR_CLOSURE,
        "ridge_exception": RIDGE_EXCEPTION,
        "leave_one_unit_out": {
            "remove_prior_closure": {
                "supportive_units_remaining": 0,
                "retained": False,
            },
            "remove_ridge_exception": {
                "supportive_units_remaining": 0,
                "retained": False,
            },
        },
        "leave_one_target_out": {
            "remove_ETC-USDT": {"bilateral_support": False},
            "remove_FIL-USDT": {"bilateral_support": False},
        },
        "failure_taxonomy": {
            "sparse_fit_support": ["ETC-USDT", "FIL-USDT"],
            "fit_to_validation_reversal": ["ETC-USDT", "FIL-USDT"],
            "benchmark_suppression": ["ETC-USDT", "FIL-USDT"],
            "turnover_amplification": ["ETC-USDT", "FIL-USDT"],
        },
        "controls": {
            key: False
            for key in (
                "new_market_data_accessed",
                "new_target_labels_accessed",
                "new_oos_accessed",
                "credentials_accessed",
                "accounts_accessed",
                "orders_placed",
                "leverage_used",
                "synthetic_market_data",
                "non_1h_input",
                "cross_sectional_selection",
                "pairs_or_spreads",
                "post_hoc_target_filtering",
                "canonical_strategy_mutated",
                "paper_trading_authorized",
                "live_trading_authorized",
            )
        },
        "remaining_blocker": (
            "Fixed linear own-history selectors have not transported from fit to validation "
            "without suppressing profitable benchmark exposure or amplifying turnover."
        ),
        "next_strategy_experiment": (
            "causal-own-price-mixture-e-process-trend-evidence-selector-1h-v1"
        ),
    }

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    payloads = {
        "evidence.json": canonical_json(evidence),
        "source-records.json": canonical_json(
            {
                "prior_closure": PRIOR_CLOSURE,
                "ridge_exception": {
                    key: RIDGE_EXCEPTION[key]
                    for key in (
                        "issue",
                        "pr",
                        "family_id",
                        "exact_head",
                        "workflow",
                        "artifact",
                        "artifact_zip_sha256",
                        "evidence_sha256",
                        "report_sha256",
                        "verdict",
                    )
                },
            }
        ),
        "report.md": build_report(evidence).encode(),
    }
    for filename, payload in payloads.items():
        (output / filename).write_bytes(payload)
        (output / f"{filename}.sha256").write_text(sha256(payload) + "\n")

    print(f"verdict={VERDICT}")
    print(f"tested_head={args.tested_head}")
    print("bound_units=2; supportive=0; closure_gates=1/12")
    print(f"evidence_sha256={sha256(payloads['evidence.json'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
