#!/usr/bin/env python3
"""Verify frozen source artifacts and checked-in metric extraction for family closure."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

REPO = "Dingding-leo/GPT"
API_VERSION = "2022-11-28"
EXPECTED = (
    {
        "architecture": "bocpd_duration_transition",
        "artifact_id": 8810093353,
        "artifact_zip_sha256": "f6b3c5727ace3017d335438002a8e401d669a29738db119629bb435077a68b49",
        "evidence_sha256": "81d56dedc27907cf3917f93c2eccdafe9dc9e8217f58f773adacfb8f713e35f8",
        "family_id": "bocpd-duration-transition-ensemble-1h-v1",
        "issue": 833,
        "pr": 832,
        "source_head": "255947db255574689e54d6f9b821675a0795693d",
        "local_filename": "bocpd-duration-transition.zip",
    },
    {
        "architecture": "multi_horizon_local_linear",
        "artifact_id": 8810786934,
        "artifact_zip_sha256": "e5663cce5a70c4324768658c1384183f9a76fad06b8543a44778118484a07948",
        "evidence_sha256": "3348f235a52ba08e30433e1203aec83f36740d00569534b85772c54ce807a333",
        "family_id": "multi-horizon-local-linear-trend-ensemble-1h-v1",
        "issue": 835,
        "pr": 836,
        "source_head": "3a3fde39e740bb672e463cc1f5c318207137d141",
        "local_filename": "local-linear-trend-ensemble.zip",
    },
    {
        "architecture": "online_specialist_arbitration",
        "artifact_id": 8811607454,
        "artifact_zip_sha256": "9879fa5ec89749995ba36d8c0cacdc07230bc6f098da6541c27790ed626e095a",
        "evidence_sha256": "d8cbd139ac3db0bd4a42a944646098f552001d78ca36d338998226524bb0d6af",
        "family_id": "transaction-cost-aware-online-specialist-arbitration-1h-v1",
        "issue": 839,
        "pr": 840,
        "source_head": "bbb9ddea4edc099e0d1b34ac7eb794514d039725",
        "local_filename": "specialist-arbitration.zip",
    },
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download_artifact(artifact_id: int, token: str) -> bytes:
    url = f"https://api.github.com/repos/{REPO}/actions/artifacts/{artifact_id}/zip"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "gpt-adaptive-overlay-source-verifier",
            "X-GitHub-Api-Version": API_VERSION,
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def parse_hash_line(raw: bytes, expected_name: str) -> str:
    line = raw.decode("utf-8").strip()
    digest, name = line.split(maxsplit=1)
    if PurePosixPath(name).name != expected_name:
        raise AssertionError(f"unexpected hash target {name!r}; expected {expected_name!r}")
    if len(digest) != 64:
        raise AssertionError(f"invalid SHA-256 {digest!r}")
    return digest


def verify_zip(spec: dict[str, Any], raw_zip: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    actual_zip_sha = sha256(raw_zip)
    if actual_zip_sha != spec["artifact_zip_sha256"]:
        raise AssertionError(
            f"artifact {spec['artifact_id']} ZIP SHA mismatch: {actual_zip_sha}"
        )
    with tempfile.TemporaryDirectory() as temporary:
        archive_path = Path(temporary, "artifact.zip")
        archive_path.write_bytes(raw_zip)
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
            basenames: dict[str, str] = {}
            for name in names:
                if name.endswith("/"):
                    continue
                basename = PurePosixPath(name).name
                if basename in basenames:
                    raise AssertionError(f"duplicate archive basename {basename!r}")
                basenames[basename] = name
            required = {
                "artifact-files.sha256",
                "evidence.json",
                "evidence.sha256",
                "materialized_source.py",
                "report.md",
                "stdout.json",
            }
            if required - basenames.keys():
                raise AssertionError(
                    f"artifact {spec['artifact_id']} missing {sorted(required - basenames.keys())}"
                )
            evidence_bytes = archive.read(basenames["evidence.json"])
            evidence_sha = sha256(evidence_bytes)
            if evidence_sha != spec["evidence_sha256"]:
                raise AssertionError(
                    f"artifact {spec['artifact_id']} evidence SHA mismatch: {evidence_sha}"
                )
            declared_evidence_sha = parse_hash_line(
                archive.read(basenames["evidence.sha256"]), "evidence.json"
            )
            if declared_evidence_sha != evidence_sha:
                raise AssertionError(
                    f"artifact {spec['artifact_id']} evidence.sha256 does not bind evidence.json"
                )
            manifest_raw = archive.read(basenames["artifact-files.sha256"])
            manifest_results = []
            for line in manifest_raw.decode("utf-8").splitlines():
                if not line.strip():
                    continue
                digest, declared_path = line.split(maxsplit=1)
                basename = PurePosixPath(declared_path).name
                if basename not in basenames:
                    raise AssertionError(
                        f"artifact {spec['artifact_id']} manifest target {basename!r} absent"
                    )
                actual = sha256(archive.read(basenames[basename]))
                if actual != digest:
                    raise AssertionError(
                        f"artifact {spec['artifact_id']} internal SHA mismatch for {basename}"
                    )
                manifest_results.append(
                    {"file": basename, "sha256": actual, "verified": True}
                )
            evidence = json.loads(evidence_bytes)
    verification = {
        "architecture": spec["architecture"],
        "artifact_id": spec["artifact_id"],
        "artifact_zip_sha256": actual_zip_sha,
        "evidence_sha256": evidence_sha,
        "internal_manifest_sha256": sha256(manifest_raw),
        "internal_files": sorted(manifest_results, key=lambda item: item["file"]),
    }
    return evidence, verification


def compact_metrics(metric: dict[str, Any], arbitration: bool = False) -> dict[str, float]:
    if arbitration:
        return {
            "annualised_arithmetic_mean": metric["annualised_arithmetic_mean"],
            "edge_per_turnover": metric["edge_per_turnover"],
            "exposure": metric["exposure_fraction"],
            "maximum_drawdown": metric["maximum_drawdown"],
            "net": metric["net_total_return"],
            "sharpe": metric["annualised_sharpe"],
            "turnover": metric["one_way_turnover"],
        }
    return {
        "annualised_arithmetic_mean": metric["annualised_arithmetic_mean"],
        "edge_per_turnover": metric["edge_per_turnover"],
        "exposure": metric["exposure"],
        "maximum_drawdown": metric["max_drawdown"],
        "net": metric["net_total_return"],
        "sharpe": metric["sharpe"],
        "turnover": metric["turnover"],
    }


def brief_metrics(metric: dict[str, Any], arbitration: bool = False) -> dict[str, float]:
    if arbitration:
        return {
            "net": metric["net_total_return"],
            "sharpe": metric["annualised_sharpe"],
        }
    return {"net": metric["net_total_return"], "sharpe": metric["sharpe"]}


def concentration(fold_returns: list[float]) -> float:
    positive = [value for value in fold_returns if value > 0]
    return max(positive) / sum(positive) if positive else 0.0


def normalise_bocpd(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for symbol, market in sorted(evidence["markets"].items()):
        segments = market["segments"]
        breadth = market["breadth"]
        train = segments["train"]["candidate"]
        oos = segments["oos"]["candidate"]
        full = segments["full"]["candidate"]
        source = market["source"]
        bootstrap = market["bootstrap_vs_trend"]
        rows.append(
            {
                "architecture": "bocpd_duration_transition",
                "benchmark_oos": compact_metrics(segments["oos"]["trend"]),
                "breadth": {
                    "fold_count": len(breadth["fold_returns"]),
                    "positive_fold_concentration": concentration(
                        breadth["fold_returns"]
                    ),
                    "positive_folds": breadth["positive_folds"],
                    "positive_years": breadth["positive_years"],
                    "year_count": breadth["year_count"],
                },
                "candidate": {
                    "full": brief_metrics(full),
                    "oos": compact_metrics(oos),
                    "train": brief_metrics(train),
                },
                "decomposition": None,
                "paired_mean_ci95": bootstrap["mean_hourly_delta_ci"],
                "paired_sharpe_ci95": bootstrap["sharpe_delta_ci"],
                "rows": source["rows"],
                "sign_reversal": train["net_total_return"] * oos["net_total_return"] < 0,
                "source_sha256": source["canonical_sha256"],
                "symbol": symbol,
            }
        )
    return rows


def normalise_local_linear(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for symbol, market in sorted(evidence["markets"].items()):
        breadth = market["breadth"]
        train = market["train"]["candidate"]
        oos = market["oos"]["candidate"]
        full = market["full"]["candidate"]
        source = market["source"]
        bootstrap = market["bootstrap_vs_trend"]
        rows.append(
            {
                "architecture": "multi_horizon_local_linear",
                "benchmark_oos": compact_metrics(market["oos"]["trend"]),
                "breadth": {
                    "fold_count": len(breadth["fold_returns"]),
                    "positive_fold_concentration": breadth[
                        "positive_fold_concentration"
                    ],
                    "positive_folds": breadth["positive_folds"],
                    "positive_years": breadth["positive_years"],
                    "year_count": breadth["year_count"],
                },
                "candidate": {
                    "full": brief_metrics(full),
                    "oos": compact_metrics(oos),
                    "train": brief_metrics(train),
                },
                "decomposition": {
                    "fee_drag_difference": market["candidate_minus_trend_decomposition"][
                        "arithmetic_fee_drag_delta"
                    ],
                    "gross_timing_return_difference": market[
                        "candidate_minus_trend_decomposition"
                    ]["arithmetic_gross_timing_delta"],
                    "net_return_difference": market[
                        "candidate_minus_trend_decomposition"
                    ]["arithmetic_gross_timing_delta"]
                    - market["candidate_minus_trend_decomposition"][
                        "arithmetic_fee_drag_delta"
                    ],
                },
                "paired_mean_ci95": [
                    value / 10_000 for value in bootstrap["mean_hourly_delta_ci_bps"]
                ],
                "paired_sharpe_ci95": bootstrap["sharpe_delta_ci"],
                "rows": source["rows"],
                "sign_reversal": train["net_total_return"] * oos["net_total_return"] < 0,
                "source_sha256": source["canonical_sha256"],
                "symbol": symbol,
            }
        )
    return rows


def normalise_arbitration(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for symbol, market in sorted(evidence["markets"].items()):
        segments = market["segments"]
        train = segments["training"]["candidate"]
        oos = segments["oos"]["candidate"]
        full = segments["full"]["candidate"]
        breadth = market["oos_breadth"]
        years = breadth["years"]
        uncertainty = market["oos_uncertainty"]["E2160"]
        source = market["source"]
        rows.append(
            {
                "architecture": "online_specialist_arbitration",
                "benchmark_oos": compact_metrics(
                    segments["oos"]["benchmarks"]["E2160"], arbitration=True
                ),
                "breadth": {
                    "fold_count": len(breadth["folds"]),
                    "positive_fold_concentration": breadth[
                        "positive_fold_concentration"
                    ],
                    "positive_folds": breadth["positive_folds"],
                    "positive_years": breadth["positive_years"],
                    "year_count": len(years),
                },
                "candidate": {
                    "full": brief_metrics(full, arbitration=True),
                    "oos": compact_metrics(oos, arbitration=True),
                    "train": brief_metrics(train, arbitration=True),
                },
                "decomposition": segments["oos"]["decomposition_vs_static"]["E2160"],
                "paired_mean_ci95": uncertainty[
                    "mean_hourly_net_difference_ci95"
                ],
                "paired_sharpe_ci95": uncertainty[
                    "annualised_sharpe_difference_ci95"
                ],
                "rows": source["rows"],
                "sign_reversal": train["net_total_return"] * oos["net_total_return"] < 0,
                "source_sha256": source["normalized_rows_sha256"],
                "symbol": symbol,
            }
        )
    return rows


def assert_equal(actual: Any, expected: Any, path: str = "root") -> int:
    if isinstance(expected, bool) or expected is None or isinstance(expected, str):
        if actual != expected:
            raise AssertionError(f"{path}: {actual!r} != {expected!r}")
        return 1
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        if not math.isclose(float(actual), float(expected), rel_tol=1e-12, abs_tol=1e-12):
            raise AssertionError(f"{path}: {actual!r} != {expected!r}")
        return 1
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            raise AssertionError(f"{path}: list shape mismatch")
        return sum(
            assert_equal(a, e, f"{path}[{index}]")
            for index, (a, e) in enumerate(zip(actual, expected, strict=True))
        )
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            raise AssertionError(f"{path}: expected dictionary")
        missing = expected.keys() - actual.keys()
        if missing:
            raise AssertionError(f"{path}: missing keys {sorted(missing)}")
        return sum(
            assert_equal(actual[key], value, f"{path}.{key}")
            for key, value in expected.items()
        )
    raise TypeError(f"unsupported value at {path}: {type(expected)}")


def architecture_identity(spec: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "architecture",
        "artifact_id",
        "artifact_zip_sha256",
        "evidence_sha256",
        "family_id",
        "issue",
        "pr",
        "source_head",
    )
    expected = {key: spec[key] for key in keys}
    actual = {key: row[key] for key in keys}
    assert_equal(actual, expected, f"architectures.{spec['architecture']}")
    return expected


def verify_source_metrics(
    source_metrics: dict[str, Any], evidences: dict[str, dict[str, Any]]
) -> tuple[int, list[dict[str, Any]]]:
    architecture_rows = {
        row["architecture"]: row for row in source_metrics["architectures"]
    }
    if set(architecture_rows) != {spec["architecture"] for spec in EXPECTED}:
        raise AssertionError("source_metrics architecture set changed")
    identities = []
    checked = 0
    for spec in EXPECTED:
        identities.append(architecture_identity(spec, architecture_rows[spec["architecture"]]))
        checked += 8
    extracted = (
        normalise_bocpd(evidences["bocpd_duration_transition"])
        + normalise_local_linear(evidences["multi_horizon_local_linear"])
        + normalise_arbitration(evidences["online_specialist_arbitration"])
    )
    expected_rows = {
        (row["architecture"], row["symbol"]): row
        for row in source_metrics["markets"]
    }
    actual_rows = {(row["architecture"], row["symbol"]): row for row in extracted}
    if set(expected_rows) != set(actual_rows):
        raise AssertionError("source_metrics market set changed")
    for key in sorted(expected_rows):
        expected = expected_rows[key]
        actual = actual_rows[key]
        # Compare the complete frozen extraction contract, while allowing derived
        # fields appended later by the meta-analysis to remain outside the source file.
        selected_expected = {name: expected[name] for name in actual}
        checked += assert_equal(actual, selected_expected, f"markets.{key[0]}.{key[1]}")
    return checked, identities


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument(
        "--source-metrics",
        type=Path,
        default=Path(__file__).with_name("source_metrics.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN", "")
    if args.artifact_dir is None and not token:
        raise SystemExit("GITHUB_TOKEN is required when --artifact-dir is omitted")
    source_metrics = json.loads(args.source_metrics.read_text(encoding="utf-8"))
    evidences: dict[str, dict[str, Any]] = {}
    artifacts = []
    for spec in EXPECTED:
        if args.artifact_dir is None:
            raw_zip = download_artifact(spec["artifact_id"], token)
            source = "github_actions_api"
        else:
            artifact_path = args.artifact_dir / spec["local_filename"]
            raw_zip = artifact_path.read_bytes()
            source = "local_artifact_dir"
        evidence, verification = verify_zip(spec, raw_zip)
        if evidence["family_id"] != spec["family_id"]:
            raise AssertionError(
                f"artifact {spec['artifact_id']} family identity mismatch"
            )
        verification["source"] = source
        artifacts.append(verification)
        evidences[spec["architecture"]] = evidence
    metrics_checked, identities = verify_source_metrics(source_metrics, evidences)
    result = {
        "schema_version": 1,
        "repository": REPO,
        "artifact_count": len(artifacts),
        "market_count": len(source_metrics["markets"]),
        "source_metrics_sha256": sha256(args.source_metrics.read_bytes()),
        "metric_identity_checks": metrics_checked,
        "architectures": identities,
        "artifacts": artifacts,
        "passed": True,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(result, indent=2, sort_keys=True) + "\n").encode()
    args.output.write_bytes(raw)
    print(json.dumps({"passed": True, "sha256": sha256(raw)}, sort_keys=True))


if __name__ == "__main__":
    main()
