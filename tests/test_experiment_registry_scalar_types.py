from __future__ import annotations

from pathlib import Path

import pytest

from gpt_quant.experiment_registry import validate_manifest_entry
from gpt_quant.reproducibility import canonical_json_sha256, file_sha256

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc"
_CANDLES = _FIXTURE_ROOT / "candles.csv"
_RAW = _FIXTURE_ROOT / "raw.json"
_METADATA = _FIXTURE_ROOT / "metadata.json"
_EXPERIMENT_KEYS = (
    "schema_version",
    "code_commit",
    "config_sha256",
    "data_sha256",
    "instrument_id",
    "bar",
    "candidate_count",
    "result_classification",
)
_RUN_KEYS = ("experiment_id", "recorded_at_utc", "artifact_sha256")


def _entry(*, candidate_count: int = 27) -> dict[str, object]:
    experiment_evidence: dict[str, object] = {
        "schema_version": 1,
        "code_commit": "a" * 40,
        "config_sha256": canonical_json_sha256(
            {"provider": "OKX", "instrument_id": "BTC-USDT", "bar": "1Dutc"}
        ),
        "data_sha256": {
            "normalized_csv": file_sha256(_CANDLES),
            "raw_pages": file_sha256(_RAW),
        },
        "instrument_id": "BTC-USDT",
        "bar": "1Dutc",
        "candidate_count": candidate_count,
        "result_classification": "fixture-only type validation; no performance claim",
    }
    experiment_id = f"exp-{canonical_json_sha256(experiment_evidence)[:24]}"
    run_evidence = {
        "experiment_id": experiment_id,
        "recorded_at_utc": "2026-07-21T15:01:16.374294+00:00",
        "artifact_sha256": {"fixture_metadata": file_sha256(_METADATA)},
    }
    return {
        **experiment_evidence,
        **run_evidence,
        "run_id": f"run-{canonical_json_sha256(run_evidence)[:24]}",
    }


def _rebind_ids(entry: dict[str, object]) -> None:
    experiment_evidence = {key: entry[key] for key in _EXPERIMENT_KEYS}
    entry["experiment_id"] = f"exp-{canonical_json_sha256(experiment_evidence)[:24]}"
    run_evidence = {key: entry[key] for key in _RUN_KEYS}
    entry["run_id"] = f"run-{canonical_json_sha256(run_evidence)[:24]}"


@pytest.mark.parametrize(
    ("invalid", "canonical"),
    [("27", 27), (27.9, 27), (True, 1)],
)
def test_registry_rejects_coerced_candidate_count(
    invalid: object,
    canonical: int,
) -> None:
    entry = _entry(candidate_count=canonical)
    entry["candidate_count"] = invalid

    with pytest.raises(ValueError, match="candidate_count must be a positive integer"):
        validate_manifest_entry(entry)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("instrument_id", 123, "instrument_id must be a non-empty string"),
        ("bar", 1, "bar must be a non-empty string"),
        (
            "result_classification",
            False,
            "result_classification must be a non-empty string",
        ),
    ],
)
def test_registry_rejects_non_string_experiment_labels(
    field: str,
    value: object,
    message: str,
) -> None:
    entry = _entry()
    entry[field] = value
    _rebind_ids(entry)

    with pytest.raises(ValueError, match=message):
        validate_manifest_entry(entry)


def test_registry_rejects_integer_commit_that_stringifies_as_hex() -> None:
    entry = _entry()
    entry["code_commit"] = "1" * 40
    _rebind_ids(entry)
    entry["code_commit"] = int("1" * 40)

    with pytest.raises(ValueError, match="code_commit must be a non-empty string"):
        validate_manifest_entry(entry)


def test_registry_rejects_integer_digest_that_stringifies_as_sha256() -> None:
    entry = _entry()
    entry["config_sha256"] = "1" * 64
    _rebind_ids(entry)
    entry["config_sha256"] = int("1" * 64)

    with pytest.raises(ValueError, match="config_sha256 must be a SHA-256 digest string"):
        validate_manifest_entry(entry)


def test_registry_rejects_non_string_hash_mapping_key() -> None:
    entry = _entry()
    digest = file_sha256(_CANDLES)
    entry["data_sha256"] = {"1": digest}
    _rebind_ids(entry)
    entry["data_sha256"] = {1: digest}

    with pytest.raises(ValueError, match="data_sha256 keys must be non-empty strings"):
        validate_manifest_entry(entry)
