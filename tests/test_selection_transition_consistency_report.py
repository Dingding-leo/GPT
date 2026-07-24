from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).parents[1]
ANALYSIS_PATH = ROOT / "reports/research/selection-transition-consistency/analysis.py"
RESULT_PATH = ROOT / "reports/research/selection-transition-consistency/result.json"
# Derived only from immutable OKX rolling OOS artifacts from workflow 29895819965,
# artifact 8519944587. The underlying return-file hashes are asserted in result.json.
REAL_FOLD_EXTRACT = {
    "BTC-USDT": {
        "parameters": [
            [90, 10, 0.85],
            [90, 2, 0.85],
            [30, 2, 0.85],
            [30, 2, 0.85],
            [30, 2, 0.7],
            [30, 2, 0.85],
            [30, 2, 0.85],
            [30, 2, 0.85],
            [30, 2, 0.85],
            [30, 2, 0.85],
            [30, 2, 0.85],
            [30, 2, 0.85],
            [90, 2, 0.7],
            [30, 10, 0.85],
            [30, 10, 0.85],
            [90, 10, 0.7],
            [30, 10, 0.85],
            [180, 10, 0.7],
            [30, 10, 0.85],
            [30, 10, 0.85],
            [30, 10, 0.85],
            [90, 10, 0.85],
            [90, 5, 0.85],
            [90, 5, 0.85],
            [90, 10, 0.85],
            [90, 10, 0.85],
        ],
        "fold_means_from_fold2": [
            -0.00036983902593208076,
            0.0007650880230278443,
            0.008259898529074543,
            0.0014943817604974802,
            -0.00062341829099586,
            0.0015123778826977572,
            0.000629003422939402,
            -9.558392123877e-06,
            -0.0010686726232234714,
            -0.0002315201398781802,
            -0.001356062391541941,
            0.0008850858815500246,
            0.0006445358447471792,
            -0.00031389978069453574,
            0.001958636328288947,
            0.002184862118444354,
            0.0009970050760953687,
            -0.0010990479539781173,
            0.0030326830340254253,
            -0.0011414861852317947,
            -7.42374396947996e-05,
            0.0006014251613860694,
            -0.0003903346522177675,
            0.0,
            -0.0011668641356202708,
        ],
    },
    "ETH-USDT": {
        "parameters": [
            [90, 10, 0.7],
            [90, 2, 0.55],
            [90, 2, 0.55],
            [30, 10, 0.85],
            [30, 10, 0.85],
            [30, 10, 0.85],
            [30, 10, 0.85],
            [30, 5, 0.85],
            [30, 5, 0.85],
            [30, 5, 0.85],
            [30, 2, 0.85],
            [180, 2, 0.85],
            [90, 5, 0.7],
            [180, 10, 0.55],
            [90, 10, 0.55],
            [90, 10, 0.55],
            [90, 10, 0.55],
            [180, 2, 0.85],
            [180, 2, 0.85],
            [90, 2, 0.85],
            [30, 10, 0.85],
            [30, 10, 0.85],
            [30, 5, 0.85],
            [30, 5, 0.85],
            [30, 5, 0.85],
            [30, 10, 0.85],
        ],
        "fold_means_from_fold2": [
            0.0004725603798999379,
            0.00016042836795654932,
            0.004897104689403604,
            0.0018086378670893438,
            0.0013802498092464368,
            0.0015320232174173862,
            0.00014468436161099246,
            0.0005105093132317463,
            -0.0013990637431375908,
            0.00021961309435053554,
            -0.00030332355894035427,
            0.0006985573416721484,
            0.0007699173029864315,
            -0.0002933388392016276,
            0.0003991714125636023,
            -0.0003851113347655296,
            0.0016746870246392984,
            -0.0029106741160452912,
            0.0011571785064309799,
            -0.0007851751592010707,
            0.0014548078952971602,
            0.0029933175803185208,
            -0.00045928168656515414,
            -0.0011900162464282078,
            -0.0005769151160252115,
        ],
    },
}
EXTRACT_SHA256 = "4916038cf72f04539010feb7a558509e100073b551b42091ce22b1bd1fbad673"


def _load_analysis():
    spec = importlib.util.spec_from_file_location("selection_transition_analysis", ANALYSIS_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load analysis module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical_extract_sha256() -> str:
    payload = (json.dumps(REAL_FOLD_EXTRACT, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return hashlib.sha256(payload).hexdigest()


def test_transition_labels_and_point_means_match_real_fold_extract() -> None:
    analysis = _load_analysis()
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))

    assert _canonical_extract_sha256() == EXTRACT_SHA256
    for market, extract in REAL_FOLD_EXTRACT.items():
        parameters = [tuple(value) for value in extract["parameters"]]
        labels = np.asarray(analysis.classify_parameter_transitions(parameters), dtype=bool)
        fold_means = np.asarray(extract["fold_means_from_fold2"], dtype=float)

        assert len(labels) == len(fold_means) == 25
        assert int(labels.sum()) == 13
        assert int((~labels).sum()) == 12
        changed = float(fold_means[labels].mean() * analysis.ANNUALIZATION)
        unchanged = float(fold_means[~labels].mean() * analysis.ANNUALIZATION)
        regimes = result["markets"][market]["regimes"]
        assert regimes["changed"]["annualized_arithmetic_mean"] == pytest.approx(changed)
        assert regimes["unchanged"]["annualized_arithmetic_mean"] == pytest.approx(unchanged)


def test_fold_blocks_are_deterministic_and_preserve_observed_pairs() -> None:
    analysis = _load_analysis()
    extract = REAL_FOLD_EXTRACT["BTC-USDT"]
    parameters = [tuple(value) for value in extract["parameters"]]
    labels = np.asarray(analysis.classify_parameter_transitions(parameters), dtype=bool)
    fold_means = np.asarray(extract["fold_means_from_fold2"], dtype=float)
    first = analysis.moving_block_indices(25, block_length=3, resamples=5, seed=17)
    second = analysis.moving_block_indices(25, block_length=3, resamples=5, seed=17)

    np.testing.assert_array_equal(first, second)
    observed_pairs = set(zip(labels, fold_means, strict=True))
    sampled_pairs = zip(labels[first[0]], fold_means[first[0]], strict=True)
    assert all(pair in observed_pairs for pair in sampled_pairs)
    for sample in first:
        for start in range(0, 24, 3):
            np.testing.assert_array_equal(np.diff(sample[start : start + 3]), np.ones(2))


def test_committed_result_records_complete_single_candidate_rejection() -> None:
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))

    assert result["candidate_count"] == 1
    assert len(result["candidates"]) == 1
    assert result["verdict"] == "reject"
    assert result["canonical_signature"].endswith("candidate_count=1")
    assert result["provenance"]["source_artifact_id"] == 8519944587
    assert result["provenance"]["tested_base_sha"] == ("18ba522be8a7bf3941392a8acfc7f5100172fc91")
    assert set(result["markets"]) == {"BTC-USDT", "ETH-USDT"}
    for market in result["markets"].values():
        assert market["classified_folds"] == 25
        assert market["excluded_folds"] == 1
        assert market["regimes"]["changed"]["folds"] == 13
        assert market["regimes"]["unchanged"]["folds"] == 12
        assert market["regimes"]["changed"]["passes"] is True
        assert market["regimes"]["unchanged"]["passes"] is False
    assert len(result["failure_reasons"]) == 2
