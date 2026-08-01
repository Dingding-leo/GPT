#!/usr/bin/env python3
"""Deterministic closure of three rejected adaptive temporal overlays."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
from pathlib import Path

SEED = 20260801
RESAMPLES = 100_000
FEE = 0.0005
PARENT = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
VERDICT = "reject_adaptive_temporal_overlay_architecture_family"
METRICS = ("mean_hourly_net", "sharpe", "drawdown", "edge_per_turnover")


def pct(x):
    return f"{100 * x:+.4f}%"


def bp(x):
    return f"{10000 * x:+.4f}"


def percentile(v, p):
    v = sorted(v)
    q = (len(v) - 1) * p
    lo = math.floor(q)
    hi = math.ceil(q)
    return v[lo] if lo == hi else v[lo] * (hi - q) + v[hi] * (q - lo)


def ci(v):
    return [percentile(v, 0.025), percentile(v, 0.975)]


def sign_p(k, n):
    return sum(math.comb(n, j) for j in range(k, n + 1)) / 2**n


def load():
    p = Path(__file__).with_name("source_metrics.json")
    d = json.loads(p.read_text(encoding="utf-8"))
    assert len(d["architectures"]) == 3 and len(d["markets"]) == 6
    assert {a["artifact_zip_sha256"] for a in d["architectures"]} == {
        "f6b3c5727ace3017d335438002a8e401d669a29738db119629bb435077a68b49",
        "e5663cce5a70c4324768658c1384183f9a76fad06b8543a44778118484a07948",
        "9879fa5ec89749995ba36d8c0cacdc07230bc6f098da6541c27790ed626e095a",
    }
    return d


def load_source_verification(path):
    verification = json.loads(path.read_text(encoding="utf-8"))
    assert verification["passed"] is True
    assert verification["artifact_count"] == 3
    assert verification["market_count"] == 6
    assert verification["metric_identity_checks"] > 100
    assert len(verification["source_metrics_sha256"]) == 64
    return verification


def compute(source_verification):
    d = load()
    ms = d["markets"]
    arch = d["architectures"]
    for r in ms:
        c, b = r["candidate"]["oos"], r["benchmark_oos"]
        r["effects"] = {
            "mean_hourly_net": (c["annualised_arithmetic_mean"] - b["annualised_arithmetic_mean"])
            / 8760,
            "sharpe": c["sharpe"] - b["sharpe"],
            "drawdown": c["maximum_drawdown"] - b["maximum_drawdown"],
            "edge_per_turnover": c["edge_per_turnover"] - b["edge_per_turnover"],
            "turnover_ratio": c["turnover"] / b["turnover"],
        }
        r["paired_both_lower_positive"] = (
            r["paired_mean_ci95"][0] > 0 and r["paired_sharpe_ci95"][0] > 0
        )
        q = r["breadth"]
        r["breadth_qualified"] = (
            q["positive_folds"] >= 4
            and q["positive_years"] == q["year_count"]
            and q["positive_fold_concentration"] <= 0.5
        )
    for a in arch:
        mm = [r for r in ms if r["architecture"] == a["architecture"]]
        assert len(mm) == 2
        for m in (*METRICS, "turnover_ratio"):
            a["median_" + m] = statistics.median(r["effects"][m] for r in mm)
    rng = random.Random(SEED)
    draws = {m: {"market": [], "architecture": []} for m in METRICS}
    for _ in range(RESAMPLES):
        aa = [arch[rng.randrange(3)] for _ in range(3)]
        sm = [r for a in aa for r in ms if r["architecture"] == a["architecture"]]
        for m in METRICS:
            draws[m]["market"].append(statistics.median(r["effects"][m] for r in sm))
            draws[m]["architecture"].append(statistics.median(a["median_" + m] for a in aa))
    agg = {}
    for m in METRICS:
        mv = [r["effects"][m] for r in ms]
        av = [a["median_" + m] for a in arch]
        loo = []
        for omit in arch:
            kept = [a["median_" + m] for a in arch if a["architecture"] != omit["architecture"]]
            loo.append(
                {"omitted_architecture": omit["architecture"], "median": statistics.median(kept)}
            )
        agg[m] = {
            "market_median": statistics.median(mv),
            "architecture_median": statistics.median(av),
            "market_mean_sensitivity": statistics.mean(mv),
            "architecture_mean_sensitivity": statistics.mean(av),
            "positive_market_count": sum(x > 0 for x in mv),
            "positive_architecture_count": sum(x > 0 for x in av),
            "market_sign_p": sign_p(sum(x > 0 for x in mv), 6),
            "architecture_sign_p": sign_p(sum(x > 0 for x in av), 3),
            "market_median_ci95": ci(draws[m]["market"]),
            "architecture_median_ci95": ci(draws[m]["architecture"]),
            "leave_one_architecture_out": loo,
            "minimum_leave_one_architecture_out_median": min(x["median"] for x in loo),
        }
    breadth = sum(r["breadth_qualified"] for r in ms)
    paired = sum(r["paired_both_lower_positive"] for r in ms)
    verified_artifacts = {
        (a["architecture"], a["artifact_id"]): (
            a["artifact_zip_sha256"],
            a["evidence_sha256"],
        )
        for a in source_verification["artifacts"]
    }
    expected_artifacts = {
        (a["architecture"], a["artifact_id"]): (
            a["artifact_zip_sha256"],
            a["evidence_sha256"],
        )
        for a in arch
    }
    identity = (
        source_verification["passed"] is True
        and verified_artifacts == expected_artifacts
        and all(
            len(a["source_head"]) == 40
            and len(a["artifact_zip_sha256"]) == 64
            and len(a["evidence_sha256"]) == 64
            for a in arch
        )
        and all(
            r["rows"] == 24144
            and len(r["source_sha256"]) == 64
            and r["benchmark_oos"]["turnover"] > 0
            for r in ms
        )
    )
    gates = {
        "market_net_5_of_6": agg["mean_hourly_net"]["positive_market_count"] >= 5,
        "market_sharpe_5_of_6": agg["sharpe"]["positive_market_count"] >= 5,
        "all_architecture_medians_net_and_sharpe_positive": agg["mean_hourly_net"][
            "positive_architecture_count"
        ]
        == 3
        and agg["sharpe"]["positive_architecture_count"] == 3,
        "cluster_bootstrap_lower_bounds_net_and_sharpe_positive": agg["mean_hourly_net"][
            "architecture_median_ci95"
        ][0]
        > 0
        and agg["sharpe"]["architecture_median_ci95"][0] > 0,
        "all_leave_one_out_net_and_sharpe_positive": agg["mean_hourly_net"][
            "minimum_leave_one_architecture_out_median"
        ]
        > 0
        and agg["sharpe"]["minimum_leave_one_architecture_out_median"] > 0,
        "drawdown_and_edge_improve_4_of_6": agg["drawdown"]["positive_market_count"] >= 4
        and agg["edge_per_turnover"]["positive_market_count"] >= 4,
        "breadth_qualified_4_of_6": breadth >= 4,
        "paired_lower_bounds_positive_4_of_6": paired >= 4,
        "architecture_median_turnover_ratio_at_most_2": all(
            a["median_turnover_ratio"] <= 2 for a in arch
        ),
        "artifact_metric_fee_and_replay_identity": identity,
    }
    return {
        "family_id": "adaptive-temporal-overlay-family-closure-1h-v1",
        "classification": "architecture_family_closure_meta_analysis",
        "research_parent": PARENT,
        "candidate_count": 0,
        "source_candidate_count": 3,
        "source_market_effect_count": 6,
        "parameter_grid_count": 0,
        "bar": "1H",
        "fee_one_way": FEE,
        "new_market_data": False,
        "new_oos_consumption": False,
        "provider": "anonymous Binance public SPOT monthly archives",
        "source_period": "2023-04-01T00:00:00Z/2025-12-31T23:00:00Z",
        "boundaries": {
            "warmup": [0, 2160],
            "training": [2160, 10800],
            "oos": [10800, 23760],
            "full": [2160, 23760],
            "suffix": [23760, 24144],
        },
        "source_artifact_verification": source_verification,
        "source_artifacts": arch,
        "source_markets": ms,
        "aggregation": agg,
        "bootstrap": {
            "seed": SEED,
            "resamples": RESAMPLES,
            "unit": "architecture_pair_preserving_both_markets",
            "limitation": "Only three architecture clusters; support is discrete and minimum possible one-sided architecture sign-test p-value is 0.125.",  # noqa: E501
        },
        "breadth_audit": {"qualified_market_count": breadth, "total": 6},
        "source_uncertainty_audit": {"both_lower_bounds_positive_count": paired, "total": 6},
        "mechanism_audit": {
            "train_to_oos_sign_reversal_count": sum(r["sign_reversal"] for r in ms),
            "calibration_to_utility_mismatch": ["BNBUSDT", "VETUSDT"],
            "trend_timing_dilution": ["XTZUSDT", "ZECUSDT"],
            "stale_realised_utility_chasing": ["KAVAUSDT", "RUNEUSDT"],
        },
        "extraction_repair": {
            "defect": "Uniform extraction failed because source artifacts used incompatible segment and metric names.",  # noqa: E501
            "repair": "Architecture-specific adapters canonicalised BOCPD nested paths, local-linear direct segments, arbitration benchmark maps and metric aliases.",  # noqa: E501
            "strategy_values_changed": False,
        },
        "gates": gates,
        "gates_passed": sum(gates.values()),
        "gates_total": len(gates),
        "accepted": False,
        "verdict": VERDICT,
        "disposition": {
            "canonical_mutation": False,
            "merge_authorised": False,
            "paper_live_authority": None,
            "same_family_rescue": False,
        },
        "remaining_blocker": "Adaptive wrappers have not replicated positive incremental net timing over fixed 2160H trend; median effects, uncertainty, breadth, edge efficiency and turnover transport fail.",  # noqa: E501
        "next_experiment": "Direct causal multiresolution Haar temporal-basis next-24H fee-clearing long/cash process on a fresh immutable 1H cohort, with training-frozen regularisation and no endpoint-trend wrapper or adaptive expert selection.",  # noqa: E501
    }


def render(e):
    A = {x["architecture"]: x for x in e["source_artifacts"]}
    g = e["aggregation"]
    L = [
        "# Adaptive temporal-overlay family closure",
        "",
        f"`{e['verdict']}` — gates {e['gates_passed']}/{e['gates_total']}; zero new candidates; 3 source architectures; 6 market effects; 1H; exactly 5 bps one way.",  # noqa: E501
        "",
        "| Architecture | Market | Candidate OOS net | Trend net | Candidate/Trend Sharpe | Net bp/h | Sharpe Δ | DD Δ | Edge/turn Δ | Turn ratio |",  # noqa: E501
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in e["source_markets"]:
        c, b, x = r["candidate"]["oos"], r["benchmark_oos"], r["effects"]
        L.append(
            f"| {A[r['architecture']]['display']} | {r['symbol']} | {pct(c['net'])} | {pct(b['net'])} | {c['sharpe']:+.4f}/{b['sharpe']:+.4f} | {bp(x['mean_hourly_net'])} | {x['sharpe']:+.4f} | {pct(x['drawdown'])} | {pct(x['edge_per_turnover'])} | {x['turnover_ratio']:.3f} |"  # noqa: E501
        )
    L += [
        "",
        "## Train / OOS / full candidate metrics",
        "",
        "| Market | Train net/Sharpe | OOS net/Sharpe | Full net/Sharpe | OOS DD | Turn | Exposure | Edge/turn |",  # noqa: E501
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in e["source_markets"]:
        c = r["candidate"]
        o = c["oos"]
        L.append(
            f"| {r['symbol']} | {pct(c['train']['net'])}/{c['train']['sharpe']:+.4f} | {pct(o['net'])}/{o['sharpe']:+.4f} | {pct(c['full']['net'])}/{c['full']['sharpe']:+.4f} | {pct(o['maximum_drawdown'])} | {o['turnover']:.0f} | {o['exposure']:.4f} | {pct(o['edge_per_turnover'])} |"  # noqa: E501
        )
    L += [
        "",
        "## Architecture aggregation",
        "",
        "| Architecture | Net bp/h | Sharpe | DD Δ | Edge/turn Δ | Turn ratio |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for a in e["source_artifacts"]:
        L.append(
            f"| {a['display']} | {bp(a['median_mean_hourly_net'])} | {a['median_sharpe']:+.4f} | {pct(a['median_drawdown'])} | {pct(a['median_edge_per_turnover'])} | {a['median_turnover_ratio']:.3f} |"  # noqa: E501
        )
    n, s = g["mean_hourly_net"], g["sharpe"]
    L += [
        "",
        f"Architecture median net **{bp(n['architecture_median'])} bp/h**, 95% CI **[{bp(n['architecture_median_ci95'][0])}, {bp(n['architecture_median_ci95'][1])}]**; median Sharpe **{s['architecture_median']:+.4f}**, 95% CI **[{s['architecture_median_ci95'][0]:+.4f}, {s['architecture_median_ci95'][1]:+.4f}]**.",  # noqa: E501
        f"Positive market net/Sharpe effects: {n['positive_market_count']}/6 and {s['positive_market_count']}/6; positive architecture medians: {n['positive_architecture_count']}/3 and {s['positive_architecture_count']}/3. Exact sign p-values: market {n['market_sign_p']:.6f}; architecture {n['architecture_sign_p']:.6f}.",  # noqa: E501
        "",
        "## Uncertainty and breadth",
        "",
        "| Market | Mean CI bp/h | Sharpe CI | Folds | Years | Concentration |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in e["source_markets"]:
        q = r["breadth"]
        L.append(
            f"| {r['symbol']} | [{bp(r['paired_mean_ci95'][0])},{bp(r['paired_mean_ci95'][1])}] | [{r['paired_sharpe_ci95'][0]:+.4f},{r['paired_sharpe_ci95'][1]:+.4f}] | {q['positive_folds']}/6 | {q['positive_years']}/{q['year_count']} | {q['positive_fold_concentration']:.4f} |"  # noqa: E501
        )
    L += [
        "",
        f"Both paired lower bounds positive: {e['source_uncertainty_audit']['both_lower_bounds_positive_count']}/6. Fold/year/concentration qualified: {e['breadth_audit']['qualified_market_count']}/6.",  # noqa: E501
        "",
        "## Failure and repair",
        "",
        "BOCPD calibration did not transport to utility; local-linear timing diluted slow trend with extreme turnover; specialist arbitration helped RUNE locally but chased stale utility on KAVA. Two of six candidates reversed train-to-OOS net sign.",  # noqa: E501
        "The first uniform extractor failed on incompatible source schemas. Architecture-specific adapters repaired field mapping only; no source metric, candidate, fee, inclusion, bootstrap, gate or verdict changed.",  # noqa: E501
        "",
        "## Gates",
    ]
    L += [f"- {k}: **{'PASS' if v else 'FAIL'}**" for k, v in e["gates"].items()]
    L += [
        "",
        "Canonical unchanged; no merge, paper or live authority; same-family rescue prohibited.",
        "",
        f"**Remaining blocker:** {e['remaining_blocker']}",
        "",
        f"**Next experiment:** {e['next_experiment']}",
    ]
    return "\n".join(L) + "\n"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--source-verification", type=Path, required=True)
    a = p.parse_args()
    e = compute(load_source_verification(a.source_verification))
    a.output_dir.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(e, indent=2, sort_keys=True) + "\n").encode()
    (a.output_dir / "evidence.json").write_bytes(raw)
    (a.output_dir / "evidence.sha256").write_text(
        hashlib.sha256(raw).hexdigest() + "  evidence.json\n", encoding="utf-8"
    )
    (a.output_dir / "report.md").write_text(render(e), encoding="utf-8")
    print(json.dumps({"gates_passed": e["gates_passed"], "verdict": e["verdict"]}, sort_keys=True))


if __name__ == "__main__":
    main()
