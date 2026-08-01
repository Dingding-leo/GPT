#!/usr/bin/env python3
# ruff: noqa: E501
"""Deterministic completed-evidence closure for issue #886."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

FAMILY_ID = "causal-distributed-slow-trend-representation-family-closure-1h-v1"
VERDICT = "reject_causal_distributed_slow_trend_representation_family"
PARENT = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
OUT = Path("reports/experiments/distributed-slow-trend-representation-family-closure-1h-v1")

SOURCE_RECORDS = json.loads(
    r'''[
{"group":"A","architecture":"block-local robust path estimator","family":"robust-block-slope-breadth-hysteresis-1h-v1","issue":637,"pr":638,"exact_head":"adfa2b65b2a1dd84409534501c27331cbf3f4b6c","provider":"OKX public confirmed SPOT","markets":["BTC-USDT","ETH-USDT"],"bar":"1H","fee_bps_one_way":5.0,"sample":{"rows_per_market":43941,"training":[2880,17520],"oos":[17520,43440],"full":[2880,43440],"folds":12,"years":4},"metrics":{"BTC-USDT":{"candidate":{"training":[-0.3223,-0.474,-0.5879,115.0,-24.57],"oos":[1.4674,1.026,-0.3550,113.0,96.99],"full":[0.6721,0.489,-0.5879,228.0,35.67]},"e2160":{"training":[-0.4129,-0.840,-0.5592,28.0,-159.81],"oos":[1.1968,0.954,-0.2655,45.0,212.75],"full":[0.2897,0.332,-0.5592,73.0,69.85]},"breadth":[5,12,2,4,0.3177],"lower_bounds":[-0.1704,-0.546]},"ETH-USDT":{"candidate":{"training":[-0.4118,-0.562,-0.5791,99.0,-39.16],"oos":[0.2563,0.396,-0.5759,90.0,57.89],"full":[-0.2611,0.066,-0.5791,189.0,7.05]},"e2160":{"training":[-0.4059,-0.584,-0.5695,23.0,-168.77],"oos":[0.7452,0.646,-0.4777,30.0,283.58],"full":[0.0368,0.233,-0.5695,53.0,87.28]},"breadth":[6,12,2,4,0.2352],"lower_bounds":[-0.3657,-0.835]}},"dimensions":{"source_complete_causal_exact_fee":true,"bilateral_positive_oos":true,"bilateral_e2160_return_and_sharpe_superiority":false,"bilateral_positive_dependence_bounds":false,"bilateral_breadth_and_concentration":false,"bilateral_turnover_and_edge_efficiency":false,"latency_or_transport_support":false},"mechanism":"BTC point improvement required 2.51x E2160 turnover and worse drawdown; ETH failed replication and full-sample transport."},
{"group":"B","architecture":"three-estimator same-horizon consensus","family":"three-estimator-slow-trend-consensus-1h-v1","issue":639,"pr":640,"exact_head":"752dfe2276b3c95fba0ae50689f17cb72651b89d","provider":"OKX public confirmed SPOT","markets":["BTC-USDT","ETH-USDT"],"bar":"1H","fee_bps_one_way":5.0,"sample":{"rows_per_market":43941,"training":[2880,17520],"oos":[17520,43440],"full":[2880,43440],"folds":12,"years":4},"metrics":{"BTC-USDT":{"candidate":{"training":[-0.4809,-1.083,-0.5810,50.0,-114.38],"oos":[0.7151,0.709,-0.3246,67.0,105.74],"full":[-0.1096,0.089,-0.5810,117.0,11.67]},"e2160":{"training":[-0.4129,-0.840,-0.5592,28.0,-159.81],"oos":[1.1968,0.954,-0.2655,45.0,212.75],"full":[0.2897,0.332,-0.5592,73.0,69.85]},"breadth":[4,12,3,4,0.3626],"lower_bounds":[-0.1864,-0.557]},"ETH-USDT":{"candidate":{"training":[-0.3699,-0.491,-0.4937,43.0,-76.30],"oos":[0.5467,0.555,-0.4931,58.0,125.42],"full":[-0.0255,0.201,-0.4979,101.0,39.54]},"e2160":{"training":[-0.4059,-0.584,-0.5695,23.0,-168.77],"oos":[0.7452,0.646,-0.4777,30.0,283.58],"full":[0.0368,0.233,-0.5695,53.0,87.28]},"breadth":[6,12,3,4,0.2379],"lower_bounds":[-0.1357,-0.313]}},"dimensions":{"source_complete_causal_exact_fee":true,"bilateral_positive_oos":true,"bilateral_e2160_return_and_sharpe_superiority":false,"bilateral_positive_dependence_bounds":false,"bilateral_breadth_and_concentration":false,"bilateral_turnover_and_edge_efficiency":false,"latency_or_transport_support":false},"mechanism":"Only 4.81% BTC and 2.78% ETH disagreement with E2160, but those rare disagreements were adverse and both full candidate returns were negative."},
{"group":"C","architecture":"multi-horizon fractional trend agreement","family":"multi-horizon-fractional-trend-ensemble-1h-v1","issue":651,"pr":652,"exact_head":"89212ce08eef8b89b23977eeec1fa53c2edb83be","provider":"OKX public confirmed SPOT","markets":["BTC-USDT","ETH-USDT"],"bar":"1H","fee_bps_one_way":5.0,"sample":{"rows_per_market":43941,"training":[2880,17520],"oos":[17520,43440],"full":[2880,43440],"folds":12,"years":4},"metrics":{"BTC-USDT":{"candidate":{"training":[-0.2451,-0.441,-0.4846,35.33,-59.99],"oos":[1.1204,0.975,-0.2931,62.33,143.37],"full":[0.6006,0.487,-0.4846,97.67,69.80]},"e2160":{"training":[-0.4129,-0.840,-0.5592,28.0,-159.81],"oos":[1.1968,0.954,-0.2655,45.0,212.75],"full":[0.2897,0.332,-0.5592,73.0,69.85]},"breadth":[4,12,3,4,0.3210],"lower_bounds":[-0.1512,-0.372]},"ETH-USDT":{"candidate":{"training":[-0.2522,-0.324,-0.3984,38.67,-48.80],"oos":[1.2751,0.904,-0.4156,55.33,189.73],"full":[0.7014,0.493,-0.4156,94.0,91.61]},"e2160":{"training":[-0.4059,-0.584,-0.5695,23.0,-168.77],"oos":[0.7452,0.646,-0.4777,30.0,283.58],"full":[0.0368,0.233,-0.5695,53.0,87.28]},"breadth":[6,12,3,4,0.2546],"lower_bounds":[-0.1423,-0.240]}},"dimensions":{"source_complete_causal_exact_fee":true,"bilateral_positive_oos":true,"bilateral_e2160_return_and_sharpe_superiority":false,"bilateral_positive_dependence_bounds":false,"bilateral_breadth_and_concentration":false,"bilateral_turnover_and_edge_efficiency":false,"latency_or_transport_support":false},"mechanism":"ETH point improvement failed uncertainty and efficiency gates; BTC lost return and the one-third exposure state lost money in both markets."},
{"group":"D","architecture":"adjacent-window temporal stochastic dominance","family":"causal-temporal-stochastic-dominance-trend-1h-v1","issue":882,"pr":884,"exact_head":"f9c71b89e816d88049dd819eb0a30caa61f4e3ac","provider":"Binance public monthly SPOT archives and checksums","markets":["ICXUSDT","ONTUSDT"],"bar":"1H","fee_bps_one_way":5.0,"sample":{"rows_per_market":24144,"training":[2160,10800],"oos":[10800,23760],"full":[2160,23760],"folds":6,"years":2},"source":{"workflow_run":30704188150,"artifact_id":8819797922,"artifact_sha256":"a6589d2666fb4a634e5f3949cbfb527d78e5b07c25e83935572bd94baaa5da55","evidence_sha256":"025f3a155189fe0f27c47d287db087439b231c3bb671b3aece35e17874d80680","verified_objects":132},"metrics":{"ICXUSDT":{"candidate":{"training":[-0.3938387057072945,-0.41132534404774407,-0.6556634432556325,4.0,-688.059076191005],"oos":[0.1552901184734563,0.4674510880927461,-0.5038775120801928,4.0,1068.887719387025],"full":[-0.2997078465025582,0.09608319514018429,-0.6960020682835879,8.0,190.4143215980101]},"e2160":{"training":[-0.1780954515858253,0.10444721252416332,-0.4951550176615662,12.0,63.93268189383887],"oos":[-0.10705692519578935,0.1875864895370691,-0.6268707482993197,16.0,107.5760035524224],"full":[-0.2660860253434736,0.15000553209699485,-0.6268707482993208,28.0,88.87172284160087]},"breadth":[3,6,1,2,0.5191580593093966],"lower_bounds":[-0.000014760731791605771,-0.2152375887532646],"delay":[0.19630652546809224,0.5055546856497248,-0.5010204081632648,4.0,1155.6280513532895]},"ONTUSDT":{"candidate":{"training":[0.6355686789828243,1.0061010156308225,-0.4414168937329698,2.0,4319.59807172656],"oos":[-0.2853088598172727,-0.04333790700129224,-0.6528542563659022,6.0,-67.84367273335812],"full":[0.1689264440293936,0.45222704207917247,-0.6528542563659019,8.0,1029.0167633816216]},"e2160":{"training":[0.28842099988365044,0.728900336030359,-0.4414168937329698,14.0,448.9744134113377],"oos":[-0.3816051708842805,-0.16745286236793414,-0.6845958519332833,30.0,-54.34853613145597],"full":[-0.2032471159478445,0.25102341083912005,-0.6845958519332827,44.0,105.79967508670563]},"breadth":[1,6,1,2,0.567249501588902],"lower_bounds":[-0.000047045115295042564,-0.6919835603001366],"delay":[-0.27346935032823905,-0.025921308876976197,-0.6489029422174721,6.0,-40.57408889041954]}},"dimensions":{"source_complete_causal_exact_fee":true,"bilateral_positive_oos":false,"bilateral_e2160_return_and_sharpe_superiority":true,"bilateral_positive_dependence_bounds":false,"bilateral_breadth_and_concentration":false,"bilateral_turnover_and_edge_efficiency":false,"latency_or_transport_support":false},"mechanism":"Both markets inverted training-to-OOS sign; ONT OOS and one-hour delay were negative, while all lower confidence bounds remained non-positive."}
]'''
)


def canonical_bytes(value: Any) -> bytes:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return (text + "\n").encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_evidence() -> dict[str, Any]:
    keys = list(SOURCE_RECORDS[0]["dimensions"])
    counts = {
        key: sum(bool(row["dimensions"][key]) for row in SOURCE_RECORDS)
        for key in keys
    }
    audits = []
    for row in SOURCE_RECORDS:
        supportive = all(row["dimensions"].values())
        audits.append(
            {
                "group": row["group"],
                "architecture": row["architecture"],
                "dimensions": row["dimensions"],
                "supportive": supportive,
            }
        )
    support = sum(row["supportive"] for row in audits)
    leave_one_out = [
        {
            "omitted_group": omitted,
            "supportive_groups": sum(
                row["supportive"] for row in audits if row["group"] != omitted
            ),
        }
        for omitted in ["A", "B", "C", "D"]
    ]
    gates = {
        "all_sources_complete": counts["source_complete_causal_exact_fee"] == 4,
        "at_least_three_supportive": support >= 3,
        "at_least_three_bilateral_positive_oos": counts["bilateral_positive_oos"] >= 3,
        "at_least_three_e2160_superior": counts["bilateral_e2160_return_and_sharpe_superiority"] >= 3,
        "at_least_three_positive_bounds": counts["bilateral_positive_dependence_bounds"] >= 3,
        "at_least_three_breadth": counts["bilateral_breadth_and_concentration"] >= 3,
        "at_least_three_efficiency": counts["bilateral_turnover_and_edge_efficiency"] >= 3,
        "at_least_three_transport": counts["latency_or_transport_support"] >= 3,
        "leave_one_out_retains_two": all(row["supportive_groups"] >= 2 for row in leave_one_out),
    }
    assert counts == {
        "source_complete_causal_exact_fee": 4,
        "bilateral_positive_oos": 3,
        "bilateral_e2160_return_and_sharpe_superiority": 1,
        "bilateral_positive_dependence_bounds": 0,
        "bilateral_breadth_and_concentration": 0,
        "bilateral_turnover_and_edge_efficiency": 0,
        "latency_or_transport_support": 0,
    }
    assert sum(gates.values()) == 2
    return {
        "family_id": FAMILY_ID,
        "classification": "completed-evidence architecture-family closure",
        "issue": 886,
        "exact_head": os.environ.get("GITHUB_SHA", "LOCAL_UNBOUND"),
        "research_parent": PARENT,
        "architecture_group_count": 4,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "new_market_data": 0,
        "new_oos_consumed": 0,
        "bar_interval": "1H",
        "canonical_fee_bps_one_way": 5.0,
        "performance_recomputed": False,
        "market_sleeves_counted_as_independent_architectures": False,
        "cross_sectional_or_contemporaneous_selection": False,
        "credentials_private_endpoints_accounts_orders_adapters_leverage_funds": False,
        "source_records_sha256": digest(canonical_bytes(SOURCE_RECORDS)),
        "support_counts": counts,
        "supportive_groups": support,
        "group_audits": audits,
        "leave_one_group_out": leave_one_out,
        "family_gates": gates,
        "family_gates_passed": sum(gates.values()),
        "family_gate_count": len(gates),
        "accepted": False,
        "verdict": VERDICT,
        "canonical_strategy_changed": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "remaining_blocker": "No tested transformation of the trailing slow price path delivered bilateral benchmark-relative information with positive uncertainty bounds, broad temporal transport and superior edge per turnover. A new hypothesis must add materially new causal information.",
    }


def pct(value: float) -> str:
    return f"{value * 100:+.2f}%"


def report(evidence: dict[str, Any]) -> str:
    lines = [
        "# Distributed slow-trend representation family — terminal closure",
        "",
        "```text",
        f"family              {FAMILY_ID}",
        "architecture groups 4",
        "new candidates      0",
        "new data / OOS      0 / 0",
        "bar / fee           immutable public 1H / exactly 5 bps one way",
        f"exact head          {evidence['exact_head']}",
        f"supportive groups   {evidence['supportive_groups']}/4",
        f"gates passed        {evidence['family_gates_passed']}/{evidence['family_gate_count']}",
        f"verdict             {VERDICT}",
        "```",
        "",
        "The closure counts architectures rather than market sleeves and recomputes no strategy path.",
        "",
        "## Source performance",
        "",
        "Metric tuple order is net return, annualised hourly Sharpe, maximum drawdown, one-way turnover, and edge per turnover in basis points.",
        "",
    ]
    for row in SOURCE_RECORDS:
        lines.extend(
            [
                f"### Group {row['group']} — {row['architecture']}",
                "",
                f"Issue #{row['issue']}, PR #{row['pr']}, exact source head `{row['exact_head']}`.",
                "",
                "| Market | Segment | Candidate net | Sharpe | Max DD | Turnover | Edge/turn | E2160 net | Sharpe | Turnover |",
                "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for market, metrics in row["metrics"].items():
            for segment in ["training", "oos", "full"]:
                candidate = metrics["candidate"][segment]
                benchmark = metrics["e2160"][segment]
                lines.append(
                    f"| {market} | {segment} | {pct(candidate[0])} | {candidate[1]:+.3f} | {pct(candidate[2])} | {candidate[3]:.2f} | {candidate[4]:+.2f} | {pct(benchmark[0])} | {benchmark[1]:+.3f} | {benchmark[3]:.2f} |"
                )
            breadth = metrics["breadth"]
            bounds = metrics["lower_bounds"]
            lines.append(
                f"| {market} breadth/uncertainty | folds {breadth[0]}/{breadth[1]} | years {breadth[2]}/{breadth[3]} | concentration {breadth[4]:.2%} | mean L95 {bounds[0]:+.8f} | Sharpe L95 {bounds[1]:+.3f} |  |  |  |  |"
            )
        lines.extend(["", f"Failure: {row['mechanism']}", ""])
    lines.extend(
        [
            "## Family audit",
            "",
            "```text",
            f"complete causal exact-fee sources   {evidence['support_counts']['source_complete_causal_exact_fee']}/4",
            f"bilateral positive OOS              {evidence['support_counts']['bilateral_positive_oos']}/4",
            f"bilateral E2160 superiority         {evidence['support_counts']['bilateral_e2160_return_and_sharpe_superiority']}/4",
            f"positive dependence bounds          {evidence['support_counts']['bilateral_positive_dependence_bounds']}/4",
            f"fold/year breadth                   {evidence['support_counts']['bilateral_breadth_and_concentration']}/4",
            f"turnover and edge efficiency        {evidence['support_counts']['bilateral_turnover_and_edge_efficiency']}/4",
            f"latency or transport support        {evidence['support_counts']['latency_or_transport_support']}/4",
            "leave-one-group-out support          0 after every omission",
            "```",
            "",
            "Three groups had bilateral positive OOS point returns, but only one beat E2160 on return and Sharpe in both markets, and that group retained negative ONT economics. No group resolved benchmark-relative uncertainty, temporal breadth, turnover efficiency or transport.",
            "",
            "## Disposition",
            "",
            "```text",
            "architecture accepted       No",
            "candidate promoted          No",
            "canonical strategy changed  No",
            "paper/live authority        None",
            f"verdict                    {VERDICT}",
            "```",
            "",
            evidence["remaining_blocker"],
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    assert [row["group"] for row in SOURCE_RECORDS] == ["A", "B", "C", "D"]
    assert all(row["bar"] == "1H" for row in SOURCE_RECORDS)
    assert all(row["fee_bps_one_way"] == 5.0 for row in SOURCE_RECORDS)
    OUT.mkdir(parents=True, exist_ok=True)
    source_bytes = canonical_bytes(SOURCE_RECORDS)
    evidence = build_evidence()
    evidence_bytes = canonical_bytes(evidence)
    files = {
        "source-records.json": source_bytes,
        "source-records.sha256": (digest(source_bytes) + "\n").encode(),
        "evidence.json": evidence_bytes,
        "evidence.sha256": (digest(evidence_bytes) + "\n").encode(),
        "report.md": report(evidence).encode(),
    }
    for name, data in files.items():
        (OUT / name).write_bytes(data)
    manifest = {name: digest(data) for name, data in files.items()}
    (OUT / "manifest.json").write_bytes(canonical_bytes(manifest))
    print(
        json.dumps(
            {
                "exact_head": evidence["exact_head"],
                "supportive_groups": evidence["supportive_groups"],
                "family_gates_passed": evidence["family_gates_passed"],
                "verdict": evidence["verdict"],
                "evidence_sha256": digest(evidence_bytes),
                "source_records_sha256": digest(source_bytes),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
