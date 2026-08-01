#!/usr/bin/env python3
"""Deterministic completed-evidence closure for issue #886.

This script reads no market data and performs no performance recomputation.
It binds four already-completed causal 1H architecture groups into a frozen,
unweighted family-level support audit.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

FAMILY_ID = "causal-distributed-slow-trend-representation-family-closure-1h-v1"
VERDICT = "reject_causal_distributed_slow_trend_representation_family"
OUT = Path("reports/experiments/distributed-slow-trend-representation-family-closure-1h-v1")
PARENT = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def metric(net: float, sharpe: float, drawdown: float, turnover: float, edge: float) -> dict[str, float]:
    return {
        "net_return": net,
        "annualised_hourly_sharpe": sharpe,
        "maximum_drawdown": drawdown,
        "one_way_turnover": turnover,
        "edge_per_turnover_bps": edge,
    }


SOURCE_RECORDS: list[dict[str, Any]] = [
    {
        "group": "A",
        "architecture": "block-local robust path estimator",
        "primary_family_id": "robust-block-slope-breadth-hysteresis-1h-v1",
        "issue": 637,
        "pr": 638,
        "exact_head": "adfa2b65b2a1dd84409534501c27331cbf3f4b6c",
        "context_predecessor": {
            "family_id": "robust-distributed-slope-trend-1h-v1",
            "issue": 628,
            "pr": 629,
            "exact_head": "59f488271632d8dc59a57ba52cf63829b77c861b",
            "independent_vote": False,
            "diagnosis": "rolling twelve 180H boundaries caused 143 BTC and 180 ETH OOS changes versus 45 and 29 for the daily endpoint benchmark",
        },
        "provider": "OKX public confirmed SPOT",
        "markets": ["BTC-USDT", "ETH-USDT"],
        "bar": "1H",
        "canonical_fee_bps_one_way": 5.0,
        "sample": {
            "source_rows_per_market": 43941,
            "training": [2880, 17520],
            "development_oos": [17520, 43440],
            "full_scored": [2880, 43440],
            "oos_folds": 12,
            "fold_hours": 2160,
            "calendar_years": 4,
            "later_suffix_unread": True,
        },
        "source_identities": {
            "workflow_run": 30401519824,
            "BTC-USDT": {
                "artifact_id": 8704977298,
                "artifact_sha256": "22d6d0e7f5dbffe4e746f091a5ab2488e3edc7d8440fea393ee2862295cf208c",
                "csv_sha256": "92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9",
            },
            "ETH-USDT": {
                "artifact_id": 8704978112,
                "artifact_sha256": "e7107f83a4eb5059ada0bb2097aeb5ded976dc9c037f564538f5cf5b4a7dffe3",
                "csv_sha256": "2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726",
            },
        },
        "performance": {
            "BTC-USDT": {
                "candidate": {
                    "training": metric(-0.3223, -0.474, -0.5879, 115.0, -24.57),
                    "oos": metric(1.4674, 1.026, -0.3550, 113.0, 96.99),
                    "full": metric(0.6721, 0.489, -0.5879, 228.0, 35.67),
                },
                "e2160": {
                    "training": metric(-0.4129, -0.840, -0.5592, 28.0, -159.81),
                    "oos": metric(1.1968, 0.954, -0.2655, 45.0, 212.75),
                    "full": metric(0.2897, 0.332, -0.5592, 73.0, 69.85),
                },
                "breadth": {
                    "profitable_folds": 5,
                    "folds": 12,
                    "profitable_years": 2,
                    "years": 4,
                    "positive_fold_concentration": 0.3177,
                },
                "uncertainty_vs_e2160": {
                    "annualised_mean_delta_lower_95": -0.1704,
                    "sharpe_delta_lower_95": -0.546,
                },
            },
            "ETH-USDT": {
                "candidate": {
                    "training": metric(-0.4118, -0.562, -0.5791, 99.0, -39.16),
                    "oos": metric(0.2563, 0.396, -0.5759, 90.0, 57.89),
                    "full": metric(-0.2611, 0.066, -0.5791, 189.0, 7.05),
                },
                "e2160": {
                    "training": metric(-0.4059, -0.584, -0.5695, 23.0, -168.77),
                    "oos": metric(0.7452, 0.646, -0.4777, 30.0, 283.58),
                    "full": metric(0.0368, 0.233, -0.5695, 53.0, 87.28),
                },
                "breadth": {
                    "profitable_folds": 6,
                    "folds": 12,
                    "profitable_years": 2,
                    "years": 4,
                    "positive_fold_concentration": 0.2352,
                },
                "uncertainty_vs_e2160": {
                    "annualised_mean_delta_lower_95": -0.3657,
                    "sharpe_delta_lower_95": -0.835,
                },
            },
        },
        "mechanism": {
            "turnover_reduction_vs_predecessor": {"BTC-USDT": 0.21, "ETH-USDT": 0.50},
            "turnover_multiple_vs_e2160": {"BTC-USDT": 113.0 / 45.0, "ETH-USDT": 90.0 / 30.0},
            "BTC_entry_gate_degenerate": True,
            "ETH_candidate_only_hours": 1320,
            "ETH_candidate_only_gross_arithmetic_return": -0.3663,
        },
        "dimensions": {
            "source_complete_causal_exact_fee": True,
            "bilateral_positive_oos": True,
            "bilateral_e2160_return_and_sharpe_superiority": False,
            "bilateral_positive_dependence_bounds": False,
            "bilateral_breadth_and_concentration": False,
            "bilateral_turnover_and_edge_efficiency": False,
            "latency_or_transport_support": False,
        },
        "source_verdict": "reject_exact_robust_block_slope_breadth_hysteresis_family",
        "failure_mechanism": "partial BTC point improvement was purchased with excessive churn and worse drawdown; ETH replication and full-sample transport failed",
    },
    {
        "group": "B",
        "architecture": "three-estimator same-horizon consensus",
        "primary_family_id": "three-estimator-slow-trend-consensus-1h-v1",
        "issue": 639,
        "pr": 640,
        "exact_head": "752dfe2276b3c95fba0ae50689f17cb72651b89d",
        "provider": "OKX public confirmed SPOT",
        "markets": ["BTC-USDT", "ETH-USDT"],
        "bar": "1H",
        "canonical_fee_bps_one_way": 5.0,
        "sample": {
            "source_rows_per_market": 43941,
            "training": [2880, 17520],
            "development_oos": [17520, 43440],
            "full_scored": [2880, 43440],
            "oos_folds": 12,
            "calendar_years": 4,
            "later_suffix_unread": True,
        },
        "performance": {
            "BTC-USDT": {
                "candidate": {
                    "training": metric(-0.4809, -1.083, -0.5810, 50.0, -114.38),
                    "oos": metric(0.7151, 0.709, -0.3246, 67.0, 105.74),
                    "full": metric(-0.1096, 0.089, -0.5810, 117.0, 11.67),
                },
                "e2160": {
                    "training": metric(-0.4129, -0.840, -0.5592, 28.0, -159.81),
                    "oos": metric(1.1968, 0.954, -0.2655, 45.0, 212.75),
                    "full": metric(0.2897, 0.332, -0.5592, 73.0, 69.85),
                },
                "breadth": {
                    "profitable_folds": 4,
                    "folds": 12,
                    "profitable_years": 3,
                    "years": 4,
                    "positive_fold_concentration": 0.3626,
                },
                "uncertainty_vs_e2160": {
                    "annualised_mean_delta_lower_95": -0.1864,
                    "sharpe_delta_lower_95": -0.557,
                },
            },
            "ETH-USDT": {
                "candidate": {
                    "training": metric(-0.3699, -0.491, -0.4937, 43.0, -76.30),
                    "oos": metric(0.5467, 0.555, -0.4931, 58.0, 125.42),
                    "full": metric(-0.0255, 0.201, -0.4979, 101.0, 39.54),
                },
                "e2160": {
                    "training": metric(-0.4059, -0.584, -0.5695, 23.0, -168.77),
                    "oos": metric(0.7452, 0.646, -0.4777, 30.0, 283.58),
                    "full": metric(0.0368, 0.233, -0.5695, 53.0, 87.28),
                },
                "breadth": {
                    "profitable_folds": 6,
                    "folds": 12,
                    "profitable_years": 3,
                    "years": 4,
                    "positive_fold_concentration": 0.2379,
                },
                "uncertainty_vs_e2160": {
                    "annualised_mean_delta_lower_95": -0.1357,
                    "sharpe_delta_lower_95": -0.313,
                },
            },
        },
        "mechanism": {
            "candidate_disagreement_rate": {"BTC-USDT": 0.0481, "ETH-USDT": 0.0278},
            "candidate_only_gross_arithmetic_return": {"BTC-USDT": -0.1254, "ETH-USDT": -0.1174},
            "BTC_e2160_only_gross_arithmetic_return": 0.1125,
            "incremental_fee": {"BTC-USDT": 0.0110, "ETH-USDT": 0.0140},
        },
        "dimensions": {
            "source_complete_causal_exact_fee": True,
            "bilateral_positive_oos": True,
            "bilateral_e2160_return_and_sharpe_superiority": False,
            "bilateral_positive_dependence_bounds": False,
            "bilateral_breadth_and_concentration": False,
            "bilateral_turnover_and_edge_efficiency": False,
            "latency_or_transport_support": False,
        },
        "source_verdict": "reject_exact_three_estimator_slow_trend_consensus_family",
        "failure_mechanism": "rare disagreements with E2160 were adverse in both markets and added turnover; both full candidate returns were negative",
    },
    {
        "group": "C",
        "architecture": "multi-horizon fractional trend agreement",
        "primary_family_id": "multi-horizon-fractional-trend-ensemble-1h-v1",
        "issue": 651,
        "pr": 652,
        "exact_head": "89212ce08eef8b89b23977eeec1fa53c2edb83be",
        "provider": "OKX public confirmed SPOT",
        "markets": ["BTC-USDT", "ETH-USDT"],
        "bar": "1H",
        "canonical_fee_bps_one_way": 5.0,
        "sample": {
            "source_rows_per_market": 43941,
            "training": [2880, 17520],
            "development_oos": [17520, 43440],
            "full_scored": [2880, 43440],
            "oos_folds": 12,
            "calendar_years": 4,
            "later_suffix_unread": True,
        },
        "performance": {
            "BTC-USDT": {
                "candidate": {
                    "training": metric(-0.2451, -0.441, -0.4846, 35.33, -59.99),
                    "oos": metric(1.1204, 0.975, -0.2931, 62.33, 143.37),
                    "full": metric(0.6006, 0.487, -0.4846, 97.67, 69.80),
                },
                "e2160": {
                    "training": metric(-0.4129, -0.840, -0.5592, 28.0, -159.81),
                    "oos": metric(1.1968, 0.954, -0.2655, 45.0, 212.75),
                    "full": metric(0.2897, 0.332, -0.5592, 73.0, 69.85),
                },
                "breadth": {
                    "profitable_folds": 4,
                    "folds": 12,
                    "profitable_years": 3,
                    "years": 4,
                    "positive_fold_concentration": 0.3210,
                },
                "uncertainty_vs_e2160": {
                    "annualised_mean_delta_lower_95": -0.1512,
                    "sharpe_delta_lower_95": -0.372,
                },
            },
            "ETH-USDT": {
                "candidate": {
                    "training": metric(-0.2522, -0.324, -0.3984, 38.67, -48.80),
                    "oos": metric(1.2751, 0.904, -0.4156, 55.33, 189.73),
                    "full": metric(0.7014, 0.493, -0.4156, 94.0, 91.61),
                },
                "e2160": {
                    "training": metric(-0.4059, -0.584, -0.5695, 23.0, -168.77),
                    "oos": metric(0.7452, 0.646, -0.4777, 30.0, 283.58),
                    "full": metric(0.0368, 0.233, -0.5695, 53.0, 87.28),
                },
                "breadth": {
                    "profitable_folds": 6,
                    "folds": 12,
                    "profitable_years": 3,
                    "years": 4,
                    "positive_fold_concentration": 0.2546,
                },
                "uncertainty_vs_e2160": {
                    "annualised_mean_delta_lower_95": -0.1423,
                    "sharpe_delta_lower_95": -0.240,
                },
            },
        },
        "mechanism": {
            "one_third_exposure_state_profitable": {"BTC-USDT": False, "ETH-USDT": False},
            "candidate_exposure_changes": {"BTC-USDT": 177, "ETH-USDT": 154},
            "e2160_exposure_changes": {"BTC-USDT": 45, "ETH-USDT": 30},
        },
        "dimensions": {
            "source_complete_causal_exact_fee": True,
            "bilateral_positive_oos": True,
            "bilateral_e2160_return_and_sharpe_superiority": False,
            "bilateral_positive_dependence_bounds": False,
            "bilateral_breadth_and_concentration": False,
            "bilateral_turnover_and_edge_efficiency": False,
            "latency_or_transport_support": False,
        },
        "source_verdict": "reject_exact_multi_horizon_fractional_trend_ensemble_family",
        "failure_mechanism": "ETH point improvement did not survive uncertainty or efficiency gates; BTC lost return and both markets suffered adjacent-state churn",
    },
    {
        "group": "D",
        "architecture": "adjacent-window temporal stochastic dominance",
        "primary_family_id": "causal-temporal-stochastic-dominance-trend-1h-v1",
        "issue": 882,
        "pr": 884,
        "exact_head": "f9c71b89e816d88049dd819eb0a30caa61f4e3ac",
        "provider": "Binance public monthly SPOT archives with companion checksums",
        "markets": ["ICXUSDT", "ONTUSDT"],
        "bar": "1H",
        "canonical_fee_bps_one_way": 5.0,
        "sample": {
            "source_rows_per_market": 24144,
            "warmup": [0, 2160],
            "training": [2160, 10800],
            "sealed_oos": [10800, 23760],
            "full_scored": [2160, 23760],
            "oos_folds": 6,
            "fold_hours": 2160,
            "calendar_years": 2,
            "later_suffix_unread": True,
        },
        "source_identities": {
            "workflow_run": 30704188150,
            "artifact_id": 8819797922,
            "artifact_sha256": "a6589d2666fb4a634e5f3949cbfb527d78e5b07c25e83935572bd94baaa5da55",
            "evidence_sha256": "025f3a155189fe0f27c47d287db087439b231c3bb671b3aece35e17874d80680",
            "archive_and_checksum_objects_verified": 132,
        },
        "performance": {
            "ICXUSDT": {
                "candidate": {
                    "training": metric(-0.3938387057072945, -0.41132534404774407, -0.6556634432556325, 4.0, -688.059076191005),
                    "oos": metric(0.1552901184734563, 0.4674510880927461, -0.5038775120801928, 4.0, 1068.887719387025),
                    "full": metric(-0.2997078465025582, 0.09608319514018429, -0.6960020682835879, 8.0, 190.4143215980101),
                },
                "e2160": {
                    "training": metric(-0.1780954515858253, 0.10444721252416332, -0.4951550176615662, 12.0, 63.93268189383887),
                    "oos": metric(-0.10705692519578935, 0.1875864895370691, -0.6268707482993197, 16.0, 107.5760035524224),
                    "full": metric(-0.2660860253434736, 0.15000553209699485, -0.6268707482993208, 28.0, 88.87172284160087),
                },
                "breadth": {
                    "profitable_folds": 3,
                    "folds": 6,
                    "positive_relative_folds": 4,
                    "profitable_years": 1,
                    "years": 2,
                    "positive_relative_fold_concentration": 0.5191580593093966,
                },
                "uncertainty_vs_e2160": {
                    "mean_hourly_delta_lower_95": -1.4760731791605771e-05,
                    "sharpe_delta_lower_95": -0.2152375887532646,
                },
                "one_hour_delay": metric(0.19630652546809224, 0.5055546856497248, -0.5010204081632648, 4.0, 1155.6280513532895),
            },
            "ONTUSDT": {
                "candidate": {
                    "training": metric(0.6355686789828243, 1.0061010156308225, -0.4414168937329698, 2.0, 4319.59807172656),
                    "oos": metric(-0.2853088598172727, -0.04333790700129224, -0.6528542563659022, 6.0, -67.84367273335812),
                    "full": metric(0.1689264440293936, 0.45222704207917247, -0.6528542563659019, 8.0, 1029.0167633816216),
                },
                "e2160": {
                    "training": metric(0.28842099988365044, 0.728900336030359, -0.4414168937329698, 14.0, 448.9744134113377),
                    "oos": metric(-0.3816051708842805, -0.16745286236793414, -0.6845958519332833, 30.0, -54.34853613145597),
                    "full": metric(-0.2032471159478445, 0.25102341083912005, -0.6845958519332827, 44.0, 105.79967508670563),
                },
                "breadth": {
                    "profitable_folds": 1,
                    "folds": 6,
                    "positive_relative_folds": 3,
                    "profitable_years": 1,
                    "years": 2,
                    "positive_relative_fold_concentration": 0.567249501588902,
                },
                "uncertainty_vs_e2160": {
                    "mean_hourly_delta_lower_95": -4.7045115295042564e-05,
                    "sharpe_delta_lower_95": -0.6919835603001366,
                },
                "one_hour_delay": metric(-0.27346935032823905, -0.025921308876976197, -0.6489029422174721, 6.0, -40.57408889041954),
            },
        },
        "mechanism": {
            "ICX_training_to_oos_net_sign_reversal": True,
            "ONT_training_to_oos_net_sign_reversal": True,
            "ICX_full_net_positive": False,
            "ONT_one_hour_delay_positive": False,
        },
        "dimensions": {
            "source_complete_causal_exact_fee": True,
            "bilateral_positive_oos": False,
            "bilateral_e2160_return_and_sharpe_superiority": True,
            "bilateral_positive_dependence_bounds": False,
            "bilateral_breadth_and_concentration": False,
            "bilateral_turnover_and_edge_efficiency": False,
            "latency_or_transport_support": False,
        },
        "source_verdict": "reject_causal_temporal_stochastic_dominance_trend_1h_v1",
        "failure_mechanism": "training/OOS sign inversion, unresolved lower bounds, narrow breadth, negative ONT OOS economics and failed bilateral latency transport",
    },
]


def validate_source_records(records: list[dict[str, Any]]) -> None:
    assert [r["group"] for r in records] == ["A", "B", "C", "D"]
    assert len({r["primary_family_id"] for r in records}) == 4
    assert all(r["bar"] == "1H" for r in records)
    assert all(r["canonical_fee_bps_one_way"] == 5.0 for r in records)
    assert all(r["dimensions"]["source_complete_causal_exact_fee"] for r in records)
    assert all(r["source_verdict"].startswith("reject_") for r in records)
    assert records[0]["context_predecessor"]["independent_vote"] is False


def build_evidence(records: list[dict[str, Any]]) -> dict[str, Any]:
    dimension_keys = [
        "source_complete_causal_exact_fee",
        "bilateral_positive_oos",
        "bilateral_e2160_return_and_sharpe_superiority",
        "bilateral_positive_dependence_bounds",
        "bilateral_breadth_and_concentration",
        "bilateral_turnover_and_edge_efficiency",
        "latency_or_transport_support",
    ]
    counts = {
        key: sum(bool(record["dimensions"][key]) for record in records)
        for key in dimension_keys
    }
    group_audits: list[dict[str, Any]] = []
    for record in records:
        dims = record["dimensions"]
        supportive = all(bool(dims[key]) for key in dimension_keys) and not record[
            "source_verdict"
        ].startswith("reject_")
        assert supportive is False
        group_audits.append(
            {
                "group": record["group"],
                "architecture": record["architecture"],
                "dimensions": dims,
                "supportive": supportive,
                "source_verdict": record["source_verdict"],
            }
        )

    supportive_groups = sum(audit["supportive"] for audit in group_audits)
    leave_one_out = []
    for omitted in [r["group"] for r in records]:
        retained = [audit for audit in group_audits if audit["group"] != omitted]
        retained_support = sum(audit["supportive"] for audit in retained)
        leave_one_out.append(
            {
                "omitted_group": omitted,
                "retained_groups": [audit["group"] for audit in retained],
                "supportive_groups": retained_support,
                "passes_minimum_two": retained_support >= 2,
            }
        )

    family_gates = {
        "1_all_four_sources_complete_causal_exact_fee": counts[
            "source_complete_causal_exact_fee"
        ]
        == 4,
        "2_at_least_three_supportive_groups": supportive_groups >= 3,
        "3_at_least_three_bilateral_positive_oos_groups": counts[
            "bilateral_positive_oos"
        ]
        >= 3,
        "4_at_least_three_bilateral_e2160_superior_groups": counts[
            "bilateral_e2160_return_and_sharpe_superiority"
        ]
        >= 3,
        "5_at_least_three_positive_dependence_bound_groups": counts[
            "bilateral_positive_dependence_bounds"
        ]
        >= 3,
        "6_at_least_three_breadth_groups": counts[
            "bilateral_breadth_and_concentration"
        ]
        >= 3,
        "7_at_least_three_turnover_efficiency_groups": counts[
            "bilateral_turnover_and_edge_efficiency"
        ]
        >= 3,
        "8_at_least_three_latency_or_transport_groups": counts[
            "latency_or_transport_support"
        ]
        >= 3,
        "9_every_leave_one_group_out_has_two_supportive_groups": all(
            row["passes_minimum_two"] for row in leave_one_out
        ),
    }
    accepted = all(family_gates.values())
    assert accepted is False
    assert counts == {
        "source_complete_causal_exact_fee": 4,
        "bilateral_positive_oos": 3,
        "bilateral_e2160_return_and_sharpe_superiority": 1,
        "bilateral_positive_dependence_bounds": 0,
        "bilateral_breadth_and_concentration": 0,
        "bilateral_turnover_and_edge_efficiency": 0,
        "latency_or_transport_support": 0,
    }
    exact_head = os.environ.get("GITHUB_SHA", "LOCAL_UNBOUND")
    source_bytes = canonical_bytes(records)
    return {
        "family_id": FAMILY_ID,
        "classification": "completed-evidence architecture-family closure",
        "issue": 886,
        "exact_head": exact_head,
        "research_parent": PARENT,
        "architecture_group_count": 4,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "new_market_data": 0,
        "new_oos_consumed": 0,
        "bar_interval": "1H",
        "canonical_fee_bps_one_way": 5.0,
        "public_immutable_source_evidence_only": True,
        "performance_recomputed": False,
        "market_sleeves_counted_as_independent_architectures": False,
        "cross_sectional_or_contemporaneous_selection": False,
        "credentials_private_endpoints_accounts_orders_adapters_leverage_funds": False,
        "source_records_sha256": sha256_bytes(source_bytes),
        "support_counts": counts,
        "supportive_groups": supportive_groups,
        "group_audits": group_audits,
        "leave_one_group_out": leave_one_out,
        "family_gates": family_gates,
        "family_gates_passed": sum(family_gates.values()),
        "family_gate_count": len(family_gates),
        "accepted": accepted,
        "verdict": VERDICT,
        "canonical_strategy_changed": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "closed_research_paths": [
            "contiguous block-slope median, majority and breadth variants",
            "block count, length, boundary-alignment and rolling-partition rescue",
            "same-horizon endpoint, OLS and block-estimator votes or weights",
            "multi-horizon endpoint-sign fractions, weights and partial-exposure rescue",
            "Mann-Whitney, rank-sum, quantile and adjacent-window stochastic-dominance path comparisons",
            "same-family hysteresis, smoothing, threshold, holding-period, sign and market-subset rescue",
            "post-result combinations of the four completed architecture groups",
        ],
        "remaining_blocker": (
            "No tested transformation of the trailing slow price path has delivered "
            "bilateral benchmark-relative information with positive uncertainty bounds, "
            "broad fold/year transport and superior edge per turnover. New work must add "
            "materially new causal information rather than reaggregate the same path."
        ),
    }


def fmt_percent(value: float) -> str:
    return f"{value * 100:+.2f}%"


def fmt_number(value: float) -> str:
    return f"{value:+.3f}"


def render_report(evidence: dict[str, Any], records: list[dict[str, Any]]) -> str:
    lines = [
        "# Distributed slow-trend representation family — terminal closure",
        "",
        "## Scope and verdict",
        "",
        "```text",
        f"family                  {FAMILY_ID}",
        "architecture groups     4",
        "new candidates          0",
        "parameter grid          0",
        "new market data         0",
        "new OOS consumed        0",
        "bar                     completed immutable public 1H source evidence",
        "fee                     exactly 5 bps one way in every executable source",
        f"exact closure head      {evidence['exact_head']}",
        f"supportive groups       {evidence['supportive_groups']}/4",
        f"family gates passed     {evidence['family_gates_passed']}/{evidence['family_gate_count']}",
        f"verdict                 {evidence['verdict']}",
        "```",
        "",
        "The closure counts architecture groups, not market sleeves. It reads no new candles, recomputes no equity curve, consumes no new OOS observations and does not create a post-result ensemble.",
        "",
        "## Architecture support matrix",
        "",
        "| Group | Representation | Source | Positive OOS | Beats E2160 | Positive bounds | Breadth | Efficiency | Latency/transport | Supportive |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for audit in evidence["group_audits"]:
        d = audit["dimensions"]
        flag = lambda value: "Pass" if value else "Fail"
        lines.append(
            f"| {audit['group']} | {audit['architecture']} | "
            f"{flag(d['source_complete_causal_exact_fee'])} | "
            f"{flag(d['bilateral_positive_oos'])} | "
            f"{flag(d['bilateral_e2160_return_and_sharpe_superiority'])} | "
            f"{flag(d['bilateral_positive_dependence_bounds'])} | "
            f"{flag(d['bilateral_breadth_and_concentration'])} | "
            f"{flag(d['bilateral_turnover_and_edge_efficiency'])} | "
            f"{flag(d['latency_or_transport_support'])} | "
            f"{'Yes' if audit['supportive'] else 'No'} |"
        )
    lines += [
        "",
        "## Frozen source performance",
        "",
        "All percentages below are compounded net returns or maximum drawdowns from the original terminal source artifacts. No metric is recomputed here.",
        "",
    ]
    for record in records:
        lines += [
            f"### Group {record['group']} — {record['architecture']}",
            "",
            f"Source: issue #{record['issue']} / PR #{record['pr']}; exact head `{record['exact_head']}`.",
            "",
            "| Market | Segment | Candidate net | Sharpe | Max DD | Turnover | Edge/turn | E2160 net | E2160 Sharpe | E2160 turnover |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for market, market_data in record["performance"].items():
            for segment in ("training", "oos", "full"):
                c = market_data["candidate"][segment]
                b = market_data["e2160"][segment]
                lines.append(
                    f"| {market} | {segment} | {fmt_percent(c['net_return'])} | "
                    f"{fmt_number(c['annualised_hourly_sharpe'])} | "
                    f"{fmt_percent(c['maximum_drawdown'])} | {c['one_way_turnover']:.2f} | "
                    f"{c['edge_per_turnover_bps']:+.2f} bp | "
                    f"{fmt_percent(b['net_return'])} | {fmt_number(b['annualised_hourly_sharpe'])} | "
                    f"{b['one_way_turnover']:.2f} |"
                )
        lines += [
            "",
            "| Market | Profitable folds | Profitable years | Concentration | Mean-delta L95 | Sharpe-delta L95 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for market, market_data in record["performance"].items():
            breadth = market_data["breadth"]
            uncertainty = market_data["uncertainty_vs_e2160"]
            fold_text = f"{breadth['profitable_folds']}/{breadth['folds']}"
            year_text = f"{breadth['profitable_years']}/{breadth['years']}"
            concentration = breadth.get(
                "positive_fold_concentration",
                breadth.get("positive_relative_fold_concentration"),
            )
            mean_lower = uncertainty.get(
                "annualised_mean_delta_lower_95",
                uncertainty.get("mean_hourly_delta_lower_95"),
            )
            lines.append(
                f"| {market} | {fold_text} | {year_text} | {concentration:.2%} | "
                f"{mean_lower:+.8f} | {uncertainty['sharpe_delta_lower_95']:+.3f} |"
            )
        lines += ["", f"Failure mechanism: {record['failure_mechanism']}.", ""]

    lines += ["## Family gate audit", "", "| Gate | Result |", "|---|---:|"]
    for gate, passed in evidence["family_gates"].items():
        lines.append(f"| `{gate}` | {'Pass' if passed else 'Fail'} |")
    lines += [
        "",
        "```text",
        f"complete sources                 {evidence['support_counts']['source_complete_causal_exact_fee']}/4",
        f"bilateral positive OOS           {evidence['support_counts']['bilateral_positive_oos']}/4",
        f"bilateral E2160 superiority      {evidence['support_counts']['bilateral_e2160_return_and_sharpe_superiority']}/4",
        f"positive uncertainty bounds      {evidence['support_counts']['bilateral_positive_dependence_bounds']}/4",
        f"fold/year breadth                {evidence['support_counts']['bilateral_breadth_and_concentration']}/4",
        f"turnover efficiency              {evidence['support_counts']['bilateral_turnover_and_edge_efficiency']}/4",
        f"latency/transport support        {evidence['support_counts']['latency_or_transport_support']}/4",
        "leave-one-group-out support      0 after every omission",
        "```",
        "",
        "## Correct family-level inference",
        "",
        "Three groups generated positive OOS point economics in every required market, but point positivity did not translate into benchmark-relative evidence. Only the stochastic-dominance group beat E2160 on return and Sharpe bilaterally, and it did so while ONT remained absolutely negative. No group produced strictly positive bilateral dependence-aware lower bounds, no group passed the required temporal breadth, and no group improved both turnover and edge per turnover bilaterally.",
        "",
        "The common failure is not a single fee threshold. Distributed path representations either created extra transitions, made adverse rare disagreements with E2160, or inverted across markets and samples. The family therefore lacks transportable incremental information.",
        "",
        "## Disposition",
        "",
        "```text",
        "architecture accepted       No",
        "candidate promoted          No",
        "canonical strategy changed  No",
        "evidence merge authorised   No",
        "paper/live authority        None",
        f"verdict                    {evidence['verdict']}",
        "```",
        "",
        "Same-family block counts, path partitions, estimator weights, horizon weights, rank statistics, hysteresis, smoothing, sign changes and market subsets are closed on the consumed evidence programme.",
        "",
        "## Remaining blocker",
        "",
        evidence["remaining_blocker"],
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    validate_source_records(SOURCE_RECORDS)
    OUT.mkdir(parents=True, exist_ok=True)
    source_bytes = canonical_bytes(SOURCE_RECORDS)
    (OUT / "source-records.json").write_bytes(source_bytes)
    (OUT / "source-records.sha256").write_text(
        sha256_bytes(source_bytes) + "\n", encoding="utf-8"
    )
    evidence = build_evidence(SOURCE_RECORDS)
    evidence_bytes = canonical_bytes(evidence)
    (OUT / "evidence.json").write_bytes(evidence_bytes)
    (OUT / "evidence.sha256").write_text(
        sha256_bytes(evidence_bytes) + "\n", encoding="utf-8"
    )
    (OUT / "report.md").write_text(
        render_report(evidence, SOURCE_RECORDS), encoding="utf-8"
    )
    manifest = {
        path.name: sha256_bytes(path.read_bytes())
        for path in sorted(OUT.iterdir())
        if path.is_file() and path.name != "manifest.json"
    }
    (OUT / "manifest.json").write_bytes(canonical_bytes(manifest))
    print(
        json.dumps(
            {
                "exact_head": evidence["exact_head"],
                "family_id": FAMILY_ID,
                "supportive_groups": evidence["supportive_groups"],
                "family_gates_passed": evidence["family_gates_passed"],
                "verdict": evidence["verdict"],
                "evidence_sha256": sha256_bytes(evidence_bytes),
                "source_records_sha256": evidence["source_records_sha256"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
