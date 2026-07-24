from __future__ import annotations

import hashlib
import importlib.util
import json
from decimal import Decimal
from pathlib import Path

_ROOT = Path(__file__).parents[1]
_ANALYSIS_PATH = _ROOT / "reports" / "research" / "prospective-top-of-book-friction" / "analysis.py"
_PREDECLARATION_PATH = _ANALYSIS_PATH.with_name("PREDECLARATION.md")
_RESULT_PATH = _ANALYSIS_PATH.with_name("result.json")
_REPORT_PATH = _ANALYSIS_PATH.with_name("REPORT.md")
_FIXTURE_DIR = _ROOT / "tests" / "fixtures" / "okx" / "order-book-btc-usdt-docs-20210826"
_EXPECTED_FIXTURE_SHA256 = "7d12a351f8f51320d1c8beee0063557e1c90388d66ac63412bf66ca544aeb3e3"
_EXPECTED_ARTIFACT_SHA256 = "44e5a388fabb5c9367f83bf259dff9e4a8c09a3691eed17a32530126c626b0c0"


def _load_analysis():
    spec = importlib.util.spec_from_file_location("prospective_quote_friction", _ANALYSIS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_predeclared_protocol_is_fixed_and_uses_real_okx_quote_evidence() -> None:
    analysis = _load_analysis()
    predeclaration = _PREDECLARATION_PATH.read_text(encoding="utf-8")

    assert analysis.INSTRUMENTS == ("BTC-USDT", "ETH-USDT")
    assert analysis.SAMPLES_PER_INSTRUMENT == 12
    assert analysis.INTERVAL_SECONDS == 2.0
    assert analysis.MAX_ATTEMPTS == 2
    assert analysis.HALF_SPREAD_P95_LIMIT_BPS == 2.5
    assert analysis.REQUEST_RTT_P95_LIMIT_SECONDS == 1.0
    assert analysis.SERVER_RTT_P95_LIMIT_SECONDS == 1.0
    assert analysis.MAXIMUM_QUOTE_AGE_MS == 1_000
    assert analysis.MAX_ABS_CLOCK_SKEW_SECONDS == 5.0
    assert analysis.CANONICAL_SIGNATURE in predeclaration

    raw = (_FIXTURE_DIR / "response.json").read_bytes()
    metadata = json.loads((_FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["response_sha256"] == _EXPECTED_FIXTURE_SHA256
    assert hashlib.sha256(raw).hexdigest() == _EXPECTED_FIXTURE_SHA256

    payload = json.loads(raw)
    bid = Decimal(payload["data"][0]["bids"][0][0])
    ask = Decimal(payload["data"][0]["asks"][0][0])
    midpoint = (bid + ask) / Decimal(2)
    observed_half_spread_bps = (ask - bid) / midpoint * Decimal(5_000)

    assert observed_half_spread_bps > 0
    assert analysis.nearest_rank_percentile([float(observed_half_spread_bps)], 0.95) == float(
        observed_half_spread_bps
    )


def test_joint_gate_requires_every_predeclared_check() -> None:
    analysis = _load_analysis()
    real_observation = {
        "half_spread_bps": 0.06096604808569125,
        "books_round_trip_seconds": 0.1,
        "server_round_trip_seconds": 0.1,
        "quote_age_ms": 100,
        "midpoint_clock_skew_seconds": 0.0,
    }
    observations = [dict(real_observation) for _ in range(analysis.SAMPLES_PER_INSTRUMENT)]

    passing = analysis._market_summary(observations, [])
    assert passing["passes"] is True
    assert all(passing["checks"].values())

    observations[-1]["half_spread_bps"] = 3.0
    failing = analysis._market_summary(observations, [])
    assert failing["passes"] is False
    assert failing["checks"]["p95_half_spread"] is False


def test_persisted_real_result_rejects_incomplete_collection() -> None:
    analysis = _load_analysis()
    result = json.loads(_RESULT_PATH.read_text(encoding="utf-8"))
    report = _REPORT_PATH.read_text(encoding="utf-8")

    assert result["canonical_signature"] == analysis.CANONICAL_SIGNATURE
    assert result["candidate_accounting"] == {"searched": 1, "passed": 0, "rejected": 1}
    assert result["hypothesis_passes"] is False
    assert result["live_eligible"] is False
    assert result["verdict"] == "rejected"
    assert result["source_workflow"]["artifact_sha256"] == _EXPECTED_ARTIFACT_SHA256

    btc = result["markets"]["BTC-USDT"]
    eth = result["markets"]["ETH-USDT"]
    assert btc["metrics"]["observations"] == 10
    assert btc["metrics"]["unrecovered_failures"] == 2
    assert eth["metrics"]["observations"] == 11
    assert eth["metrics"]["unrecovered_failures"] == 1
    assert btc["checks"]["complete_observation_count"] is False
    assert eth["checks"]["complete_observation_count"] is False
    assert all(value for key, value in btc["checks"].items() if key != "complete_observation_count")
    assert all(value for key, value in eth["checks"].items() if key != "complete_observation_count")
    assert "midpoint clock skew does not match its timestamps" in " ".join(btc["failures"])
    assert "midpoint clock skew does not match its timestamps" in " ".join(eth["failures"])
    assert "Result: rejected" in report
