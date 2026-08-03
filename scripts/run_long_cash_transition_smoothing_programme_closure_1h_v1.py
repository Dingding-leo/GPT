from __future__ import annotations

# ruff: noqa: E501

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

FAMILY_ID = "causal-long-cash-transition-smoothing-programme-closure-1h-v1"
VERDICT = "reject_reopening_completed_long_cash_transition_smoothing_mechanisms_1h_v1"
CANONICAL_MAIN = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
FEE_BPS_ONE_WAY = 5.0


def _metrics(
    net_return: float | None,
    sharpe: float | None,
    max_drawdown: float | None,
    turnover: float | None,
    edge_per_turnover_bps: float | None,
) -> dict[str, float | None]:
    return {
        "net_return": net_return,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "turnover": turnover,
        "edge_per_turnover_bps": edge_per_turnover_bps,
    }


GROUPS: list[dict[str, Any]] = [
    {
        "group_id": "path-efficiency-state-hysteresis",
        "taxonomy": "feature_state_level_hysteresis",
        "family_id": "path-efficiency-hysteresis-1h-v1",
        "issue": 593,
        "pr": 594,
        "pr_state": "closed_unmerged",
        "exact_evidence_head": "15641559fe137648fa51ddadfea80029aa711806",
        "terminal_verdict": "reject_exact_path_efficiency_hysteresis_family",
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "source": {
            "provider": "OKX",
            "market": "SPOT",
            "bar": "1H",
            "workflow_run_id": 30401519824,
            "BTC-USDT": {
                "artifact_id": 8704977298,
                "csv_sha256": "92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9",
            },
            "ETH-USDT": {
                "artifact_id": 8704978112,
                "csv_sha256": "2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726",
            },
        },
        "protocol_identity": {
            "report_blob_sha": "092c1610ca07b936bb8c9e2f4039821156692191",
            "result_sha256": "fb8199a902ff93606fcb4dd0aa680d0f97d645002775c7d794396f2d3cc46800",
        },
        "economics": {
            "BTC-USDT": {
                "train": _metrics(0.1143322054, 0.4273107131, -0.2044565636, 13.0, 108.2192396),
                "oos": _metrics(1.1859121648, 1.2024308979, -0.2474257747, 37.0, 235.3021884),
                "full": _metrics(1.4358323234, 0.9553123363, -0.2474257747, 50.0, 202.2606217),
                "benchmark_oos": _metrics(1.2021563073, 0.9561877759, -0.2654678574, 45.0, 213.2897942),
            },
            "ETH-USDT": {
                "train": _metrics(-0.0561984677, -0.0711177805, -0.2087385758, 28.0, -8.5571340),
                "oos": _metrics(0.9426368400, 0.9183653516, -0.2880718503, 24.0, 328.7059267),
                "full": _metrics(0.8334636263, 0.6310828863, -0.2880718503, 52.0, 147.1027402),
                "benchmark_oos": _metrics(0.7451603411, 0.6456279608, -0.4776594161, 30.0, 283.5837648),
            },
        },
        "breadth": {
            "BTC-USDT": {"profitable_folds": 4, "folds": 12, "profitable_years": 2, "years": 4},
            "ETH-USDT": {"profitable_folds": 4, "folds": 12, "profitable_years": 3, "years": 4},
        },
        "uncertainty_lower_bounds": {
            "BTC-USDT": {"mean_delta": -0.2671294513, "sharpe_delta": -0.5196971415},
            "ETH-USDT": {"mean_delta": -0.4135296494, "sharpe_delta": -0.7351190633},
        },
        "delay_passed": None,
        "fully_supportive": False,
        "failure": "Sparse fold breadth, negative residual Sharpe, and non-positive paired lower bounds.",
    },
    {
        "group_id": "range-breakout-state-hysteresis",
        "taxonomy": "price_boundary_hysteresis",
        "family_id": "causal-range-breakout-hysteresis-trend-1h-v1",
        "issue": 630,
        "pr": 632,
        "pr_state": "closed_unmerged",
        "exact_evidence_head": "c246aaec10e16704fc4760dc046e9d57d4f97de3",
        "terminal_verdict": "reject_exact_causal_range_breakout_hysteresis_trend_family",
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "source": {
            "provider": "OKX",
            "market": "SPOT",
            "bar": "1H",
            "workflow_run_id": 30401519824,
            "BTC-USDT": {"artifact_id": 8704977298},
            "ETH-USDT": {"artifact_id": 8704978112},
        },
        "protocol_identity": {
            "report_blob_sha": "48c7499e6069a1f53617f67cb5107ff8aa2e4a0e",
            "result_sha256": "22dbde9c2f3586484b22be8aa827768bdf80aad23f48e6e15142191a1b3837e3",
            "script_sha256": "b0f45cdc06649be13dbe675b5287407cc60897b4731f800704b372814a1a50a2",
        },
        "economics": {
            "BTC-USDT": {
                "train": _metrics(0.2429, 0.652, -0.2173, 1.0, 2681.64),
                "oos": _metrics(1.1658, 0.937, -0.3925, 3.0, 3148.67),
                "full": _metrics(1.6919, 0.845, -0.3925, 4.0, 3031.91),
                "benchmark_oos": _metrics(1.1968, 0.954, -0.2655, 45.0, 212.75),
            },
            "ETH-USDT": {
                "train": _metrics(-0.2781, -0.179, -0.5418, 2.0, -701.93),
                "oos": _metrics(-0.4143, -0.012, -0.7050, 4.0, -53.50),
                "full": _metrics(-0.5772, -0.064, -0.7050, 6.0, -269.64),
                "benchmark_oos": _metrics(0.7452, 0.646, -0.4777, 30.0, 283.58),
            },
        },
        "breadth": {
            "BTC-USDT": {"profitable_folds": 3, "folds": 12, "profitable_years": 3, "years": 4},
            "ETH-USDT": {"profitable_folds": 6, "folds": 12, "profitable_years": 1, "years": 4},
        },
        "uncertainty_lower_bounds": {
            "BTC-USDT": {"mean_delta": -0.283873, "sharpe_delta": -0.808916},
            "ETH-USDT": {"mean_delta": -0.795515, "sharpe_delta": -1.579325},
        },
        "delay_passed": None,
        "fully_supportive": False,
        "failure": "Excessive persistence; ETH lost 41.43% OOS and the final 14,543-hour episode lost 40.64%.",
    },
    {
        "group_id": "low-frequency-trend-coherence-hysteresis",
        "taxonomy": "feature_state_level_hysteresis",
        "family_id": "low-frequency-trend-coherence-hysteresis-1h-v1",
        "issue": 634,
        "pr": 635,
        "pr_state": "closed_unmerged",
        "exact_evidence_head": "52b141f1e8f989c2ae2d1b76a3ed57be63cd14dd",
        "terminal_verdict": "reject_exact_low_frequency_trend_coherence_hysteresis_family",
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "source": {
            "provider": "OKX",
            "market": "SPOT",
            "bar": "1H",
            "workflow_run_id": 30401519824,
            "BTC-USDT": {"artifact_id": 8704977298},
            "ETH-USDT": {"artifact_id": 8704978112},
        },
        "protocol_identity": {
            "script_sha256": "9066cf6226c03bad8e4e861e430449653937af2199a9091566c59bf38b917e2d",
        },
        "economics": {
            "BTC-USDT": {
                "train": _metrics(None, None, None, None, None),
                "oos": _metrics(0.2319, 0.403, -0.3048, 10.0, 305.44),
                "full": _metrics(None, None, None, None, None),
                "benchmark_oos": _metrics(1.1968, 0.954, -0.2655, 45.0, 212.75),
            },
            "ETH-USDT": {
                "train": _metrics(None, None, None, None, None),
                "oos": _metrics(1.3385, 0.999, -0.3099, 8.0, 1285.80),
                "full": _metrics(None, None, None, None, None),
                "benchmark_oos": _metrics(0.7452, 0.646, -0.4777, 30.0, 283.58),
            },
        },
        "breadth": {
            "BTC-USDT": {"profitable_folds": 4, "folds": 12, "profitable_years": None, "years": 4},
            "ETH-USDT": {"profitable_folds": 7, "folds": 12, "profitable_years": 3, "years": 4},
        },
        "uncertainty_lower_bounds": {
            "BTC-USDT": {"mean_delta": -0.5289, "sharpe_delta": -1.485},
            "ETH-USDT": {"mean_delta": -0.2940, "sharpe_delta": -0.460},
        },
        "delay_passed": None,
        "fully_supportive": False,
        "failure": "BTC omitted profitable benchmark exposure; ETH point gains relied on four entries and lacked dependence support.",
    },
    {
        "group_id": "robust-block-slope-breadth-hysteresis",
        "taxonomy": "feature_state_level_hysteresis",
        "family_id": "robust-block-slope-breadth-hysteresis-1h-v1",
        "issue": 637,
        "pr": 638,
        "pr_state": "closed_unmerged",
        "exact_evidence_head": "adfa2b65b2a1dd84409534501c27331cbf3f4b6c",
        "terminal_verdict": "reject_exact_robust_block_slope_breadth_hysteresis_family",
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "source": {
            "provider": "OKX",
            "market": "SPOT",
            "bar": "1H",
            "workflow_run_id": 30401519824,
            "BTC-USDT": {"artifact_id": 8704977298},
            "ETH-USDT": {"artifact_id": 8704978112},
        },
        "protocol_identity": {
            "report_blob_sha": "8f3cb6f0e32e0f35229333389d4a784767d98161",
            "core_sha256": "266ce94d3d3a5d0fe2b5b4ab725efc7d02420934c7bc57e1ea8d4a9d7f0c0188",
            "runner_sha256": "fe5113c46efc68d0accdc8218c9397f3eb3513011db82608dd505b18ad57fea9",
            "result_sha256": "694931734aa00f55c5cd05d50112f4fb99a2147db335a92241cf3247169cfe02",
        },
        "economics": {
            "BTC-USDT": {
                "train": _metrics(-0.3223, -0.474, -0.5879, 115.0, -24.57),
                "oos": _metrics(1.4674, 1.026, -0.3550, 113.0, 96.99),
                "full": _metrics(0.6721, 0.489, -0.5879, 228.0, 35.67),
                "benchmark_oos": _metrics(1.1968, 0.954, -0.2655, 45.0, 212.75),
            },
            "ETH-USDT": {
                "train": _metrics(-0.4118, -0.562, -0.5791, 99.0, -39.16),
                "oos": _metrics(0.2563, 0.396, -0.5759, 90.0, 57.89),
                "full": _metrics(-0.2611, 0.066, -0.5791, 189.0, 7.05),
                "benchmark_oos": _metrics(0.7452, 0.646, -0.4777, 30.0, 283.58),
            },
        },
        "breadth": {
            "BTC-USDT": {"profitable_folds": 5, "folds": 12, "profitable_years": 2, "years": 4},
            "ETH-USDT": {"profitable_folds": 6, "folds": 12, "profitable_years": 2, "years": 4},
        },
        "uncertainty_lower_bounds": {
            "BTC-USDT": {"mean_delta": -0.1704, "sharpe_delta": -0.546},
            "ETH-USDT": {"mean_delta": -0.3657, "sharpe_delta": -0.835},
        },
        "delay_passed": None,
        "fully_supportive": False,
        "failure": "Turnover remained 2.5–3.0 times the daily benchmark and cross-market edge-per-turnover failed.",
    },
    {
        "group_id": "bocpd-posterior-probability-hysteresis",
        "taxonomy": "posterior_confidence_hysteresis",
        "family_id": "bocpd-runlength-hysteresis-1h-v1",
        "issue": 828,
        "pr": 829,
        "pr_state": "closed_unmerged",
        "exact_evidence_head": "49c53c009443842c3143675ffa09d5d48624d9ba",
        "terminal_verdict": "reject_bocpd_runlength_hysteresis_architecture_v1",
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "source": {
            "provider": "OKX",
            "market": "SPOT",
            "bar": "1H",
            "BTC-USDT": {
                "artifact_id": 8769605568,
                "csv_sha256": "40c7ba3dbf64b8b31c634a79e1a2d5e2fa9d60b024c1fd62848d37ed967c13a0",
            },
            "ETH-USDT": {
                "artifact_id": 8769619607,
                "csv_sha256": "0164a5cc1730f70ad9817980d67d6350cf71013cdb759c1a153a66890127d6f8",
            },
        },
        "protocol_identity": {
            "evidence_artifact_id": 8809213000,
            "artifact_zip_sha256": "ffcad976d2414f13e902147e7f334a25e7c4705c7643de88f5c7b4126ce34a9c",
            "evidence_json_sha256": "be01bc46b48e5eee24fe1fd4afade554fb14ebe02205ae20f90694a1f5f7b26e",
        },
        "economics": {
            "BTC-USDT": {
                "train": _metrics(0.677278, 1.3619, -0.224676, 164.0, None),
                "oos": _metrics(-0.137036, -0.3000, -0.295116, 152.0, -9.02),
                "full": _metrics(0.447430, 0.6060, -0.295116, 316.0, None),
                "benchmark_oos": _metrics(-0.065561, -0.0730, -0.203761, None, None),
            },
            "ETH-USDT": {
                "train": _metrics(0.673360, 1.2136, -0.191585, 140.0, None),
                "oos": _metrics(-0.341476, -0.5187, -0.483842, 182.0, -18.76),
                "full": _metrics(0.101948, 0.2719, -0.483842, 322.0, None),
                "benchmark_oos": _metrics(-0.123843, -0.0104, -0.436948, None, None),
            },
        },
        "breadth": {
            "BTC-USDT": {"profitable_folds": 2, "folds": 6, "profitable_years": 0, "years": 2},
            "ETH-USDT": {"profitable_folds": 2, "folds": 6, "profitable_years": 0, "years": 2},
        },
        "uncertainty_lower_bounds": {
            "BTC-USDT": {"mean_delta_bps_per_hour": -0.4204, "sharpe_delta": -1.5577},
            "ETH-USDT": {"mean_delta_bps_per_hour": -0.9563, "sharpe_delta": -2.1598},
        },
        "delay": {
            "BTC-USDT": {"net_return": -0.189124},
            "ETH-USDT": {"net_return": -0.440241},
        },
        "delay_passed": False,
        "fully_supportive": False,
        "failure": "Positive training reversed to negative OOS gross and net performance with frequent costly threshold crossings.",
    },
    {
        "group_id": "e2160-local-noise-band-hysteresis",
        "taxonomy": "price_boundary_hysteresis",
        "family_id": "causal-own-price-e2160-noise-band-hysteresis-1h-v1",
        "issue": 1008,
        "pr": 1009,
        "pr_state": "closed_unmerged",
        "exact_evidence_head": "367efc3834d678e5c1e960085dbb94d2f995b993",
        "terminal_verdict": "reject_causal_own_price_e2160_noise_band_hysteresis_1h_v1",
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "source": {
            "provider": "OKX",
            "market": "SPOT",
            "bar": "1H",
            "rows_per_target": 24144,
            "BTC-USDT": {"slice_sha256": "237fb608434516022b235b283cf5b81531fd1c91c4548ea63139f5b248cbb5dc"},
            "ETH-USDT": {"slice_sha256": "d753887e8953fda7a7334ab9aac4f230d2a3a054027923a41ad27132989c5c4a"},
        },
        "protocol_identity": {
            "focused_workflow_run": 30772706016,
            "artifact_id": 8841070461,
            "artifact_zip_sha256": "b5c0408ac7ab545f2e4371f67562543b9dd4d984f96a1e313f0cf98df08b7e4a",
            "evidence_json_sha256": "a035b4a57a1048fc1686c6c8461678a56e3d69f2d064b31d08ba298d48db9099",
        },
        "economics": {
            "BTC-USDT": {
                "train": _metrics(0.7973, 1.731, -0.2268, 10.0, 670.05),
                "oos": _metrics(0.2630, 0.643, -0.2541, 10.0, 314.38),
                "full": _metrics(1.2700, 1.114, -0.2541, 20.0, 492.21),
                "benchmark_oos": _metrics(0.4331, 0.901, -0.2159, 15.0, 293.91),
            },
            "ETH-USDT": {
                "train": _metrics(0.6989, 1.428, -0.2963, 5.0, 1286.56),
                "oos": _metrics(-0.0449, 0.185, -0.4800, 9.0, 150.52),
                "full": _metrics(0.6226, 0.659, -0.4800, 14.0, 556.25),
                "benchmark_oos": _metrics(0.0022, 0.249, -0.4424, 15.0, 120.10),
            },
        },
        "breadth": {
            "BTC-USDT": {"profitable_folds": 3, "folds": 6, "positive_relative_folds": 1, "relative_concentration": 1.0},
            "ETH-USDT": {"profitable_folds": 2, "folds": 6, "positive_relative_folds": 1, "relative_concentration": 1.0},
        },
        "uncertainty_lower_bounds": {
            "BTC-USDT": {"mean_delta": -0.0000311545, "sharpe_delta": -0.841739},
            "ETH-USDT": {"mean_delta": -0.0000155896, "sharpe_delta": -0.277875},
        },
        "delay": {
            "BTC-USDT": {"candidate_net": 0.2568, "benchmark_net": 0.3826},
            "ETH-USDT": {"candidate_net": -0.0565, "benchmark_net": 0.0178},
        },
        "delay_passed": False,
        "fully_supportive": False,
        "failure": "Fee savings were smaller than timing losses; ETH OOS became negative and relative fold effects were fully concentrated.",
    },
    {
        "group_id": "target-innovation-uncertainty-hysteresis",
        "taxonomy": "target_revision_suppression",
        "family_id": "causal-target-innovation-hysteresis-programme-closure-1h-v1",
        "issue": 1013,
        "pr": 1015,
        "pr_state": "closed_unmerged",
        "exact_evidence_head": "faa07687ae281fc4446878906599d523776c3954",
        "terminal_verdict": "reject_reopening_completed_target_innovation_hysteresis_mechanisms_1h_v1",
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "source": {
            "provider": "OKX",
            "market": "SPOT",
            "bar": "1H",
            "targets": ["BTC-USDT", "ETH-USDT", "ADA-USDT", "XRP-USDT"],
        },
        "protocol_identity": {
            "focused_workflow_run": 30777599303,
            "artifact_id": 8842562632,
            "artifact_zip_sha256": "a1b699e9be828771102ac58303a7bcd64cbaadfdcbf739a3cb42764a1493c101",
            "evidence_sha256": "7308a10ae3d9788437c33a24c1e05f28f926a3d3d60c18730e7898a21d18f1ad",
        },
        "economics": {
            "BTC-USDT": {
                "train": _metrics(None, None, None, None, None),
                "oos": _metrics(0.4637, 0.664, -0.2683, 30.65, 51.07),
                "full": _metrics(None, None, None, None, None),
                "benchmark_oos": _metrics(0.4359, 0.637, -0.2684, 45.23, 33.18),
            },
            "ETH-USDT": {
                "train": _metrics(None, None, None, None, None),
                "oos": _metrics(0.2112, 0.405, -0.2830, 45.70, 19.44),
                "full": _metrics(None, None, None, None, None),
                "benchmark_oos": _metrics(0.1631, 0.343, -0.2903, 62.38, 12.05),
            },
            "ADA-USDT": {
                "train": _metrics(-0.2403, -1.243, -0.3031, 24.54, -63.68),
                "oos": _metrics(0.0671, 0.210, -0.3208, 34.91, 11.67),
                "full": _metrics(-0.1893, -0.176, -0.3208, 31.17, -9.74),
                "benchmark_oos": _metrics(0.0405, 0.166, -0.3298, 47.92, 6.71),
            },
            "XRP-USDT": {
                "train": _metrics(-0.1277, -0.571, -0.1638, 37.84, -19.42),
                "oos": _metrics(-0.1558, -0.164, -0.2681, 43.17, -8.05),
                "full": _metrics(-0.2636, -0.262, -0.3550, 41.24, -11.82),
                "benchmark_oos": _metrics(-0.1652, -0.182, -0.2683, 54.76, -7.04),
            },
        },
        "breadth": {
            "BTC-USDT": {"profitable_folds": 4, "folds": 12},
            "ETH-USDT": {"profitable_folds": 5, "folds": 12},
            "ADA-USDT": {"profitable_folds": 4, "folds": 12},
            "XRP-USDT": {"profitable_folds": 5, "folds": 12},
        },
        "uncertainty_lower_bounds": {
            "BTC-USDT": {"edge_per_turnover_delta_bps": -9.79},
            "ETH-USDT": {"edge_per_turnover_delta_bps": -8.72},
            "ADA-USDT": {"mean_delta": 0.00000040096, "sharpe_delta": 0.01731},
            "XRP-USDT": {"mean_delta": -0.000000082296, "sharpe_delta": -0.00325},
        },
        "delay": {
            "ADA-USDT": {"relative_improvement_preserved": True},
            "XRP-USDT": {"candidate_net": -0.1512, "benchmark_net": -0.1600},
        },
        "delay_passed": False,
        "fully_supportive": False,
        "failure": "The policy suppressed revisions but external full-sample economics and edge-per-turnover remained negative.",
    },
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_with_hash(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.with_name(f"{path.name}.sha256").write_text(f"{hashlib.sha256(payload).hexdigest()}\n")


def _build_evidence(tested_head: str) -> dict[str, Any]:
    supportive = [group["group_id"] for group in GROUPS if group["fully_supportive"]]
    leave_one_group_out = [
        {
            "removed_group": group["group_id"],
            "supportive_groups_remaining": [item for item in supportive if item != group["group_id"]],
            "retains_support": any(item != group["group_id"] for item in supportive),
        }
        for group in GROUPS
    ]
    closure_gates = {
        "identities_reconcile": True,
        "two_groups_pass_original_bilateral_gates": False,
        "two_groups_bilateral_positive_oos_and_full": False,
        "two_groups_return_and_sharpe_superior": False,
        "two_groups_reduce_turnover_and_improve_edge_per_turnover": False,
        "two_groups_preserve_or_improve_drawdown": False,
        "two_groups_pass_fold_year_breadth": False,
        "two_groups_have_positive_dependence_lower_bounds": False,
        "two_groups_pass_execution_delay": False,
        "every_leave_one_group_out_subset_retains_support": False,
        "external_cohort_retains_support": False,
        "conclusion_independent_of_single_market_or_negative_base": False,
    }
    gate_pass_count = sum(closure_gates.values())
    return {
        "family_id": FAMILY_ID,
        "canonical_main": CANONICAL_MAIN,
        "tested_head": tested_head,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "new_market_data_rows": 0,
        "new_target_labels": 0,
        "new_oos_access": False,
        "canonical_fee_bps_one_way": FEE_BPS_ONE_WAY,
        "canonical_mutation": "none",
        "paper_or_live_authority": "none",
        "group_count": len(GROUPS),
        "supportive_group_count": len(supportive),
        "supportive_groups": supportive,
        "mechanism_groups": GROUPS,
        "group_support_summary": [
            {
                "group_id": group["group_id"],
                "taxonomy": group["taxonomy"],
                "terminal_verdict": group["terminal_verdict"],
                "fully_supportive": group["fully_supportive"],
                "failure": group["failure"],
            }
            for group in GROUPS
        ],
        "leave_one_group_out": leave_one_group_out,
        "leave_one_target_out_supportive_count": 0,
        "leave_one_cohort_out_supportive_count": 0,
        "closure_gates": closure_gates,
        "closure_gate_pass_count": gate_pass_count,
        "closure_gate_total": len(closure_gates),
        "closed_rescue_scope": [
            "alternate entry or exit bands, quantiles, multipliers, equality rules, or asymmetric thresholds",
            "alternate path-efficiency, coherence, breadth, posterior, or E2160-margin windows",
            "minimum holds, cooldowns, debounce rules, persistence counters, or state resets",
            "partial target adjustment, rounding, clipping, or innovation smoothing",
            "combining rejected hysteresis states",
            "changing the upstream selector after relative improvement of negative economics",
            "adding or replacing markets, deleting negative folds or years, or promoting one target",
            "treating turnover or drawdown reduction alone as transferable alpha",
        ],
        "remaining_blocker": (
            "The programme lacks a causal upstream information process with independently "
            "replicated positive economics before transition smoothing. Scalar no-trade "
            "regions either delay valuable regime changes, preserve harmful exposure, or "
            "reduce revisions on an upstream target that is itself weak."
        ),
        "verdict": VERDICT,
    }


def _pct(value: float | None) -> str:
    return "null" if value is None else f"{100.0 * value:+.2f}%"


def _num(value: float | None, digits: int = 3) -> str:
    return "null" if value is None else f"{value:.{digits}f}"


def _build_report(evidence: dict[str, Any]) -> str:
    lines = [
        "# Long/cash transition-smoothing programme closure",
        "",
        "```text",
        f"family                  {FAMILY_ID}",
        f"canonical main          {CANONICAL_MAIN}",
        f"exact evidence head     {evidence['tested_head']}",
        "bound groups           7",
        "new candidates/grid    0/0",
        "new market rows/OOS    0/0",
        f"supportive groups       {evidence['supportive_group_count']}/7",
        f"closure gates passed    {evidence['closure_gate_pass_count']}/{evidence['closure_gate_total']}",
        f"verdict                 {VERDICT}",
        "```",
        "",
        "## Strategy-facing conclusion",
        "",
        "All seven completed mechanisms reduced to the same trade-off: a wider no-trade region removed revisions, but either delayed valuable trend transitions, created excessively persistent harmful exposure, or smoothed an upstream target without transferable absolute alpha. No group passed its original bilateral promotion gates.",
        "",
        "| Group | Taxonomy | BTC OOS net / Sharpe | ETH OOS net / Sharpe | Decisive failure |",
        "|---|---|---:|---:|---|",
    ]
    for group in GROUPS:
        economics = group["economics"]
        btc = economics.get("BTC-USDT", {}).get("oos", _metrics(None, None, None, None, None))
        eth = economics.get("ETH-USDT", {}).get("oos", _metrics(None, None, None, None, None))
        lines.append(
            "| "
            + group["group_id"]
            + " | "
            + group["taxonomy"]
            + " | "
            + f"{_pct(btc['net_return'])} / {_num(btc['sharpe'])}"
            + " | "
            + f"{_pct(eth['net_return'])} / {_num(eth['sharpe'])}"
            + " | "
            + group["failure"]
            + " |"
        )
    lines.extend(
        [
            "",
            "## Turnover-efficiency adjudication",
            "",
            "- Path efficiency had attractive bilateral point estimates and lower turnover, but only 4/12 profitable folds in each market and negative dependence-aware lower bounds.",
            "- Range breakout reduced turnover to 3/4 OOS changes, but ETH remained long through a 14,543-hour losing episode and lost 41.43% OOS.",
            "- Trend coherence helped ETH but destroyed BTC benchmark timing; the apparent ETH gain arose from only four entries and remained statistically unresolved.",
            "- Block-slope breadth still traded 2.5–3.0 times the daily benchmark and reduced edge per turnover in both markets.",
            "- BOCPD posterior hysteresis was negative OOS before fees in both markets and failed the one-hour delay replay.",
            "- E2160 noise bands reduced turnover by roughly one third to two fifths but surrendered more timing return than fees saved.",
            "- Target-innovation smoothing transported as revision suppression, not alpha: ADA and XRP full-sample economics remained negative and edge per turnover worsened.",
            "",
            "## Frozen closure gates",
            "",
            "| Gate | Result |",
            "|---|---:|",
        ]
    )
    for gate, passed in evidence["closure_gates"].items():
        lines.append(f"| {gate} | {'PASS' if passed else 'FAIL'} |")
    lines.extend(
        [
            "",
            "Every leave-one-group-out subset contains zero fully supportive mechanisms. Removing the BTC/ETH development cohort also leaves no supportive external bilateral evidence set.",
            "",
            "## Performance record",
            "",
            "This closure creates no candidate path and reads no new return label or OOS observation. Historical train/OOS/full fields are copied only where they were published by the original immutable protocols; unavailable fields are explicitly null rather than zero. Exactly 5 bps one way remains bound to every historical executable path.",
            "",
            "## Verdict",
            "",
            f"`{VERDICT}`",
            "",
            "The completed scalar/band transition-smoothing programme is closed. This does not claim that every stateful decision system is ineffective; it rejects reopening these completed mechanisms through another threshold, cooldown, persistence count, minimum hold, target clip, or market-specific rescue.",
            "",
            "## Remaining blocker",
            "",
            evidence["remaining_blocker"],
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tested-head", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    if len(args.tested_head) != 40 or any(character not in "0123456789abcdef" for character in args.tested_head):
        raise ValueError("tested head must be a lowercase 40-character commit SHA")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    evidence = _build_evidence(args.tested_head)
    source_records = {
        "canonical_main": CANONICAL_MAIN,
        "tested_head": args.tested_head,
        "groups": [
            {
                "group_id": group["group_id"],
                "issue": group["issue"],
                "pr": group["pr"],
                "exact_evidence_head": group["exact_evidence_head"],
                "source": group["source"],
                "protocol_identity": group["protocol_identity"],
                "terminal_verdict": group["terminal_verdict"],
            }
            for group in GROUPS
        ],
    }
    report = _build_report(evidence)

    evidence_bytes = (json.dumps(evidence, indent=2, sort_keys=True) + "\n").encode()
    source_bytes = (json.dumps(source_records, indent=2, sort_keys=True) + "\n").encode()
    report_bytes = report.encode()

    _write_with_hash(output_dir / "evidence.json", evidence_bytes)
    _write_with_hash(output_dir / "source_records.json", source_bytes)
    _write_with_hash(output_dir / "report.md", report_bytes)

    manifest = {
        "family_id": FAMILY_ID,
        "tested_head": args.tested_head,
        "files": {
            "evidence.json": _sha256(output_dir / "evidence.json"),
            "source_records.json": _sha256(output_dir / "source_records.json"),
            "report.md": _sha256(output_dir / "report.md"),
        },
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    _write_with_hash(output_dir / "manifest.json", manifest_bytes)


if __name__ == "__main__":
    main()
