from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

import gpt_quant.reproducibility as reproducibility

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc"
_CANDLES = _FIXTURE_ROOT / "candles.csv"
_RAW = _FIXTURE_ROOT / "raw.json"
_METADATA = _FIXTURE_ROOT / "metadata.json"


def _arguments() -> dict[str, object]:
    metadata = json.loads(_METADATA.read_text(encoding="utf-8"))
    return {
        "effective_config": {
            "data": {"provider": "OKX", "instrument_id": "BTC-USDT", "bar": "1Dutc"}
        },
        "data_hashes": {
            "normalized_csv": metadata["fixture_normalized_csv_sha256"],
            "raw_pages": metadata["fixture_raw_json_sha256"],
        },
        "data_paths": {"normalized_csv": _CANDLES, "raw_pages": _RAW},
        "artifact_paths": {"fixture_metadata": _METADATA},
        "candidate_count": 27,
        "result_classification": "fixture-only scalar validation; no performance claim",
        "instrument_id": "BTC-USDT",
        "bar": "1Dutc",
        "code_commit": "c" * 40,
        "recorded_at_utc": "2026-07-21T15:01:16.374294+00:00",
    }


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"candidate_count": True}, "candidate_count must be a positive integer"),
        ({"candidate_count": 27.5}, "candidate_count must be a positive integer"),
        ({"candidate_count": "27"}, "candidate_count must be a positive integer"),
        ({"result_classification": 1}, "result_classification must be a non-empty string"),
        ({"instrument_id": 1}, "instrument_id must be a non-empty string"),
        ({"bar": 1}, "bar must be a non-empty string"),
        ({"code_commit": int("1" * 40)}, "commit id string"),
        (
            {"code_provenance": {"checkout_commit": int("1" * 40)}, "code_commit": None},
            "commit id string",
        ),
        (
            {"recorded_at_utc": datetime(2026, 7, 22, tzinfo=UTC)},
            "recorded_at_utc must be an ISO-8601 string",
        ),
        (
            {"recorded_at_utc": "2026-07-22T00:00:00Z"},
            "recorded_at_utc must use canonical UTC ISO-8601 form",
        ),
        (
            {"recorded_at_utc": "2026-07-22T09:30:00+09:30"},
            "recorded_at_utc must be expressed in UTC",
        ),
        (
            {"data_hashes": {"normalized_csv": int("1" * 64)}},
            "must be a SHA-256 digest string",
        ),
        (
            {"data_hashes": {1: "1" * 64}},
            "data_hashes keys must be non-empty strings",
        ),
        (
            {"artifact_paths": {1: _METADATA}},
            "artifact_paths keys must be non-empty strings",
        ),
    ],
)
def test_manifest_builder_rejects_scalar_coercion_before_file_io(
    overrides: dict[str, object],
    message: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments = _arguments()
    arguments.update(overrides)

    def unexpected_file_read(path: str | Path) -> str:
        pytest.fail(f"manifest builder read {path} before validating scalar types")

    monkeypatch.setattr(reproducibility, "file_sha256", unexpected_file_read)

    with pytest.raises(ValueError, match=message):
        reproducibility.build_experiment_manifest_entry(**arguments)  # type: ignore[arg-type]


def test_manifest_builder_preserves_valid_scalar_types() -> None:
    entry = reproducibility.build_experiment_manifest_entry(
        **_arguments()  # type: ignore[arg-type]
    )

    assert entry["candidate_count"] == 27
    assert type(entry["candidate_count"]) is int
    assert entry["instrument_id"] == "BTC-USDT"
    assert entry["bar"] == "1Dutc"
    assert entry["recorded_at_utc"] == "2026-07-21T15:01:16.374294+00:00"
