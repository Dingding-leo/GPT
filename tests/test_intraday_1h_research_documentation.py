from __future__ import annotations

from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_DOC_PATH = _REPOSITORY_ROOT / "docs" / "INTRADAY_1H_RESEARCH_GATE.md"
_PROFILE_TEST_PATH = _REPOSITORY_ROOT / "tests" / "test_intraday_research_profile.py"
_GRID_TEST_PATH = _REPOSITORY_ROOT / "tests" / "test_verify_intraday_1h_timestamp_grid.py"
_CROSS_MARKET_TEST_PATH = _REPOSITORY_ROOT / "tests" / "test_intraday_1h_cross_market_gate.py"


def test_operator_commands_match_current_intraday_gate_surface() -> None:
    doc = _DOC_PATH.read_text(encoding="utf-8")
    implementation_tests = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (_PROFILE_TEST_PATH, _GRID_TEST_PATH, _CROSS_MARKET_TEST_PATH)
    )

    for token in (
        "scripts/run_okx_research.py",
        "scripts/verify_intraday_1h_timestamp_grid.py",
        "scripts/verify_walk_forward_report.py",
        "scripts/verify_intraday_1h_profile.py",
        "scripts/build_intraday_1h_promotion_gate.py",
        "sha256sum --check artifact-manifest.sha256",
        "tests/test_verify_intraday_1h_timestamp_grid.py",
        "tests/test_intraday_1h_cross_market_gate.py",
    ):
        assert token in doc

    for implementation_token in (
        "verify_intraday_1h_timestamp_grid.py",
        "Build deterministic cross-market launch blockers",
        "persist-credentials: false",
        "transaction_cost_bps == 5.0",
        "cost_multipliers",
        "[1.0]",
    ):
        assert implementation_token in implementation_tests


def test_provider_byte_acceptance_is_explicitly_fail_closed() -> None:
    doc = _DOC_PATH.read_text(encoding="utf-8")

    for required in (
        "exactly **5 bps one-way exchange fee**",
        'required = {"payload", "raw_response_base64", "raw_response_sha256"}',
        "object_pairs_hook=reject_duplicates",
        "base64.b64decode(encoded, validate=True)",
        "hashlib.sha256(raw).hexdigest() != expected_sha",
        "payload differs from exact bytes",
        "exact_provider_page_bytes=passed",
        "currently generated canonical research artifacts are expected to fail",
        "parsed page mappings rather than per-page",
        "evidence_integrity_passes: true",
        "manifest can be valid while exact provider-byte provenance is still unavailable",
        "`1Dutc` benchmark",
        "`15m` is not implemented",
        "not paper-trading\nacceptance",
    ):
        assert required in doc

    assert "Do not treat a cross-market field" in doc
    assert "separate exact-byte OKX `1H` coverage boundary" in doc
    assert "prove byte/hash equality" in doc
    assert "1h source provenance remains blocked" in doc
    assert "Spread,\nslippage, market impact, and latency are not added to PnL" in doc
