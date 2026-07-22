from __future__ import annotations

from pathlib import Path

import pytest

import gpt_quant.reproducibility as reproducibility


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ({1: "integer-key"}, "keys must be strings"),
        ({"value": float("nan")}, "finite JSON numbers"),
        ({"value": float("inf")}, "finite JSON numbers"),
        ({"value": float("-inf")}, "finite JSON numbers"),
        ({"value": (1, 2)}, "JSON-native values"),
    ],
)
def test_canonical_json_hash_rejects_coerced_or_nonstandard_values(
    value: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        reproducibility.canonical_json_sha256(value)


@pytest.mark.parametrize(
    "effective_config",
    [
        {1: "integer-key"},
        {"risk": float("nan")},
        {"risk": float("inf")},
        {"grid": (1, 2)},
    ],
)
def test_manifest_builder_rejects_noncanonical_config_before_file_io(
    effective_config: dict[object, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_file_read(path: str | Path) -> str:
        pytest.fail(f"manifest builder read {path} before validating effective_config")

    monkeypatch.setattr(reproducibility, "file_sha256", unexpected_file_read)

    with pytest.raises(ValueError):
        reproducibility.build_experiment_manifest_entry(
            effective_config=effective_config,  # type: ignore[arg-type]
            data_hashes={"normalized_csv": "1" * 64, "raw_pages": "2" * 64},
            data_paths={"normalized_csv": "unused.csv", "raw_pages": "unused.json"},
            artifact_paths={"report": "unused-report.json"},
            candidate_count=27,
            result_classification="canonical JSON rejection; no market data or performance claim",
            instrument_id="BTC-USDT",
            bar="1Dutc",
            code_commit="c" * 40,
            recorded_at_utc="2026-07-21T15:01:16.374294+00:00",
        )
