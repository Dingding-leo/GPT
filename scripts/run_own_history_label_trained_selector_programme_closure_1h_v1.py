from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

FAMILY_ID = "causal-own-history-label-trained-selector-programme-closure-1h-v1"
VERDICT = (
    "reject_reopening_completed_own_history_label_trained_selector_mechanisms_1h_v1"
)
CANONICAL_MAIN = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
FEE_BPS_ONE_WAY = 5.0

GROUPS: tuple[dict[str, Any], ...] = (
    {
        "group": "dual-horizon-direct-forecast-consensus",
        "taxonomy": "point forecasting",
        "issues": [774],
        "head": "14883d9208ffb9ec6c7861da490578d21113c17c",
        "workflow": 30617994452,
        "artifact": 8788284442,
        "artifact_sha256": "286bdc58c5d895c098739af6225e68a2c468837be1a096cf90d9aa9687d30365",
        "targets": ["UNI-USDT", "AAVE-USDT"],
        "metrics": {
            "UNI": "train +50.84%/0.839; OOS -76.00%/-0.466 vs B1 +1.50%/0.364; full -63.80%/-0.128; DD -79.73%; turn 210; edge/turn -40.71bp; folds 3/12; years 0/4; mean CI [-136.55%,+14.89%]; Sharpe CI [-1.819,+0.210]",
            "AAVE": "train -5.94%/0.173; OOS -21.20%/0.165 vs B1 +54.58%/0.565; full -25.88%/0.167; DD -59.90%; turn 214; edge/turn +13.70bp; folds 4/12; years 1/4; mean CI [-102.77%,+39.56%]; Sharpe CI [-1.476,+0.652]",
        },
        "failure": "Negative forecast-realised correlations and gross timing losses in both targets.",
    },
    {
        "group": "weekly-analog-downside-bound",
        "taxonomy": "empirical-tail estimation",
        "issues": [777],
        "prs": [778],
        "head": "ba74663bd2d26b16eb4e3839c5b7d5158eb69eb2",
        "workflow": 30621276119,
        "artifact": 8789616842,
        "artifact_sha256": "cf8233594c4ac7dfb5b43f2b62a8a50836278eb7263bbb55ce8f0c485c59de80",
        "targets": ["ETC-USDT", "COMP-USDT"],
        "metrics": {
            "ETC": "0/154 OOS activations; train/OOS/full 0%; turn 0; Sharpe and edge/turn undefined; folds 0/12; years 0/4; mean CI [-83.62%,+46.07%]",
            "COMP": "0/154 OOS activations; train/OOS/full 0%; turn 0; Sharpe and edge/turn undefined; folds 0/12; years 0/4; mean CI [-50.94%,+99.50%]",
        },
        "failure": "Every conditional lower-tail estimate was negative, yielding no executable state.",
    },
    {
        "group": "trend-conditioned-weekly-loss-probability-veto",
        "taxonomy": "loss-probability estimation",
        "issues": [779],
        "prs": [780],
        "head": "7b41f013974eb205e1f0057d894108ccda45d8f8",
        "workflow": 30623640090,
        "artifact": 8790558603,
        "artifact_sha256": "e6f75c66142ee590989092b1e808c1473ec349ad92901b487d1bfdb0b081f3d9",
        "evidence_sha256": "efb6d44701d05e5ff8d8747806c2554a92c13cff7051e611781338d5c02d03a8",
        "targets": ["NEAR-USDT", "SAND-USDT"],
        "metrics": {
            "NEAR": "OOS +113.30%/0.715 vs B1 +359.98%/1.046; turn 47 vs 39; edge/turn 332.25 vs 631.76bp; full -56.64%; folds 5/12; years 2/4",
            "SAND": "OOS +28.94%/0.441 vs B1 +0.74%/0.329; full -19.65%; folds 3/12; years 2/4; concentration 79.73%; uncertainty crossed zero",
        },
        "failure": "NEAR lost benchmark carry; SAND was concentrated, unresolved and negative full sample.",
    },
    {
        "group": "payoff-efficiency-sizing-programme",
        "taxonomy": "payoff-magnitude estimation",
        "issues": [782, 785, 787],
        "prs": [783, 786, 788],
        "head": "8a48d1d5104dab1ede3717a21abb83ffe6e724a8",
        "workflow": 30629936423,
        "artifact": 8793052104,
        "artifact_sha256": "4157da8f5ad132fe5fada4c998082f4ede9697e65e034312a38f040a8dbb9585",
        "evidence_sha256": "d311b226d2bb38d26201981518b65d49d9acc64c35df6c01790b4cdf7d703f3c",
        "predecessors": [
            "782/dee134a32e03d7368bc53d5620a5aaa30a1085f5/30625205060/8791167598/9e2861743648542d88f6b908478c2914fe449122d596ead8a0cca6ff39af518d",
            "785/fe8d5776b30a04359b74088c9245c580d8f3185a/30628149914/8792363876/dcd1ae470da242aaec31632d5844af298e35d445110b3bb294eea473012e16b1",
        ],
        "targets": ["KSM-USDT", "IOTA-USDT"],
        "metrics": {
            "KSM": "OOS -11.20%/0.076 vs B1 -3.65%/0.329; turn 19.41 vs 36; edge/turn 43.20 vs 189.03bp; folds 4/12; years 2/4; residual Sharpe -0.573",
            "IOTA": "OOS +19.68%/0.350 vs B1 +11.17%/0.413; full -18.10%; turn 20.96 vs 38; edge/turn 198.07 vs 237.79bp; folds 3/12; years 2/4; concentration 76.85%; residual Sharpe -0.442",
            "common": "mean delta -18.34%, CI [-55.53%,+16.28%]; Sharpe delta -0.158, CI [-0.408,+0.065]",
        },
        "failure": "Payoff state ordering was negative bilaterally and failed breadth, uncertainty and edge efficiency.",
    },
    {
        "group": "direct-causal-haar-fee-clearing-classifier",
        "taxonomy": "fitted temporal representation",
        "issues": [844],
        "prs": [846],
        "head": "c955a6dc00e1a233de2ce4090572bc4656386ce5",
        "workflow": None,
        "artifact": None,
        "identity_note": "Exact-head runs were action_required with no jobs; immutable hashes below remain the terminal identity.",
        "source_manifest_sha256": "97de137ed169395967ca23f61cb7a79454089718806da9975a39fdf5e5039dbe",
        "training_freeze_sha256": "621339d27649aec5d508127feca35ee700c575df224a7488a98b6af7b5489d39",
        "evidence_sha256": "198900034bff50b045030efdc5862af27b096522cc45f851d9d55cdfe592700b",
        "targets": ["NEOUSDT", "IOTAUSDT"],
        "metrics": {
            "NEO": "train +127.4073%/1.601233; OOS -58.9913%/-0.528537 vs E2160 +0.9585%/0.330565; full -6.7433%/0.294967; DD -73.0444%; turn 246; edge/turn -23.98bp; folds 1/6; years 0/2; delay -35.4773%/-0.004774",
            "IOTA": "train +148.6013%/1.755720; OOS -65.8808%/-0.562686 vs E2160 +8.6063%/0.466519; full -15.1792%/0.263644; DD -70.2995%; turn 288; edge/turn -22.88bp; folds 2/6; years 0/2; delay -50.7900%/-0.332557",
        },
        "failure": "Severe bilateral train-to-OOS reversal with roughly 10.3x E2160 turnover.",
    },
    {
        "group": "historical-analog-consensus-abstention",
        "taxonomy": "recurrence lookup",
        "issues": [847],
        "prs": [849],
        "head": "03aefd91130161d933ea6955fc189ca4a5974357",
        "workflow": 30684784277,
        "artifact": 8813522789,
        "artifact_sha256": "ce1d64d7b41a70f908b58f6600ba694d88069cde91f09b57db7e11ccd7a572b3",
        "evidence_sha256": "3db15fc8490f81dc21cf24a49bb99a19c78426ee0ab6e25459653734f77fc28e",
        "targets": ["ALGOUSDT", "ATOMUSDT"],
        "metrics": {
            "ALGO": "OOS +7.4788%/0.3168 vs E2160 +93.1887%/0.9513; DD -37.5163%; turn 54; relative folds 4/6; relative years 1/2; concentration 72.2598%; delay -11.0628%/-0.0277; CIs crossed zero",
            "ATOM": "OOS +61.2151%/1.3921 vs E2160 -46.6201%/-0.4519; DD -19.4216%; turn 58; relative folds 5/6; years 2/2; concentration 34.3960%; delay -5.1384%/-0.0276; lower CIs negative",
        },
        "failure": "ATOM failed dependence and delay; ALGO failed benchmark superiority and bilateral replication.",
    },
    {
        "group": "bocpd-duration-confirmed-e2160-entry",
        "taxonomy": "posterior-feature classification",
        "issues": [897],
        "head": "4c0fddf698bd9a0cb79c7312c8b201dec2c20ccb",
        "workflow": 30711305929,
        "artifact": 8821978012,
        "artifact_sha256": "3ebb9ae7cc7249214ebd2abebb047d64087c87b9a0d7b0c65f89c3534d25c01c",
        "evidence_sha256": "7d1dd9e5fadfc4674f79317dd8882c389d5ec8004ac26c5f97c9ff99a4386315",
        "targets": ["COMPUSDT", "LINKUSDT"],
        "metrics": {
            "COMP": "train -9.0488%/-0.1616; OOS -23.8538%/-0.2998 vs E2160 -12.5652%/+0.2229; full -30.7441%/-0.2501; turn 10; DD -49.7588%; folds 1/6; mean-delta L95 -0.00014910; gates 6/16",
            "LINK": "train +26.2207%/+0.6896; OOS +41.7411%/+0.6878 vs E2160 +13.1387%/+0.4789; full +78.9066%/+0.6885; turn 12; DD -51.8306%; folds 2/6; mean-delta L95 -0.00000389; gates 10/16",
        },
        "failure": "LINK was narrow and unresolved; COMP was negative and destroyed gross timing value.",
    },
    {
        "group": "fixed-cohort-conformal-trend-utility-selector",
        "taxonomy": "conformal utility bounding",
        "issues": [1019],
        "prs": [1021],
        "head": "67216eca1b97bcf38ff8d3ed05f10953c79437f9",
        "workflow": 30782993273,
        "artifact": 8844371870,
        "artifact_sha256": "60315708142ef3ecca9950d5556062fca2ef9adcbde4bb5001b6e2d0555322ff",
        "evidence_sha256": "0b5a4646d990b1d2f89e6590e286980fe00fe0f4b15bf59fb2e8a8d4ad566b7a",
        "targets": ["BCH-USDT", "LINK-USDT"],
        "metrics": {
            "BCH": "43,941 rows; fit positive 39/330; calibration positive 132/280; OOS positive 606/1080; all economics null",
            "LINK": "43,941 rows; fit positive 62/330; calibration positive 99/280; OOS positive 520/1080; all economics null",
        },
        "failure": "Both fit-positive counts were below the frozen minimum 80, so labels and performance remained unread.",
    },
)


def canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def report(evidence: dict[str, Any]) -> str:
    lines = [
        "# Own-history label-trained selector programme closure 1H v1",
        "",
        f"`{evidence['verdict']}`",
        "",
        "| Group | Estimator | Targets | Passed | Failure |",
        "|---|---|---|---:|---|",
    ]
    for group in evidence["groups"]:
        lines.append(
            f"| {group['group']} | {group['taxonomy']} | "
            f"{', '.join(group['targets'])} | 0/2 | {group['failure']} |"
        )
    lines += [
        "",
        "No completed group passed every original bilateral promotion gate. "
        "Every leave-one-group-out subset retains zero supportive groups, and removing "
        "BTC/ETH development evidence leaves no external supportive bilateral set.",
        "",
        "The strongest isolated point estimates also fail promotion: ATOM analog fails "
        "dependence and delay; LINK BOCPD has only 2/6 profitable folds and no COMP "
        "replication; SAND veto is concentrated and negative full sample. The conformal "
        "group stopped before labels, so its economics are null rather than zero.",
        "",
        "This closure accessed no new market row, label, candidate path, benchmark path, "
        "bootstrap draw or OOS observation. Its own performance metrics are null.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tested-head", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    if len(args.tested_head) != 40 or len(GROUPS) != 8:
        raise ValueError("invalid exact-head or group count")
    if any(group.get("passed", False) for group in GROUPS):
        raise AssertionError("unexpected supportive group")
    gates = {
        "identities_reconcile": True,
        "two_bilateral_original_passes": False,
        "two_bilateral_positive_oos_full": False,
        "two_bilateral_benchmark_superiority": False,
        "two_bilateral_turnover_edge_improvement": False,
        "two_bilateral_acceptable_drawdown": False,
        "two_bilateral_breadth": False,
        "two_bilateral_positive_uncertainty": False,
        "two_bilateral_delay_passes": False,
        "leave_one_group_out_support": False,
        "external_bilateral_support": False,
        "no_sparse_or_single_target_dependence": False,
    }
    evidence = {
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
        "group_count": 8,
        "fully_supportive_group_count": 0,
        "closure_gates": gates,
        "closure_gates_passed": 1,
        "leave_one_group_out": {
            group["group"]: {"remaining_supportive_groups": 0, "retained": False}
            for group in GROUPS
        },
        "leave_one_target_out_supportive": False,
        "leave_one_cohort_out_supportive": False,
        "groups": list(GROUPS),
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
    }
    root = Path(args.output_dir)
    root.mkdir(parents=True, exist_ok=True)
    payloads = {
        "evidence.json": canonical_json(evidence),
        "source-records.json": canonical_json(
            {
                group["group"]: {
                    key: group.get(key)
                    for key in (
                        "issues",
                        "prs",
                        "head",
                        "workflow",
                        "artifact",
                        "artifact_sha256",
                        "evidence_sha256",
                        "source_manifest_sha256",
                        "training_freeze_sha256",
                        "identity_note",
                    )
                    if key in group
                }
                for group in GROUPS
            }
        ),
        "report.md": report(evidence).encode(),
    }
    for name, payload in payloads.items():
        (root / name).write_bytes(payload)
        (root / f"{name}.sha256").write_text(digest(payload) + "\n")
    print(f"verdict={VERDICT}")
    print(f"tested_head={args.tested_head}")
    print("groups=8; supportive=0; closure_gates=1/12")
    print(f"evidence_sha256={digest(payloads['evidence.json'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
