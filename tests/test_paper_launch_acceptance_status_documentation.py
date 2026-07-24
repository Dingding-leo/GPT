from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _read(*parts: str) -> str:
    return _ROOT.joinpath(*parts).read_text(encoding="utf-8")


def test_paper_launch_status_matches_current_fail_closed_gates() -> None:
    documentation = _read("docs", "PAPER_LAUNCH_ACCEPTANCE_STATUS.md")
    promotion = _read("scripts", "build_intraday_1h_promotion_gate.py")
    cross_market = _read("scripts", "build_intraday_1h_cross_market_gate.py")
    workflow = _read(".github", "workflows", "intraday-1h-research.yml")

    required_text = (
        "canonical immutable public-OKX `1H` evidence gate is now on `main`",
        "exactly **5 bps one-way exchange fee**",
        "`1Dutc` path remains the benchmark",
        "`15m` remains blocked",
        "cross_market_candidate_eligible = false",
        "allow_15m_evaluation = false",
        "allow_paper_promotion = false",
        "allow_limited_capital = false",
        "copies every manifested file into a private temporary tree",
        "The presence of these commands in documentation or a workflow definition is not",
        "A missing run is **UNVERIFIED**, not a pass or a failure.",
        "green runs cannot authorize a moved PR head",
        "Python Package Build",
        "Hourly Quant Research",
        "Canonical BTC ETH 1h Research",
        "OKX 1H Data Coverage",
        "the release decision\nremains **BLOCKED** and G1 must not start",
        "IMPLEMENTED; EXACT-HEAD EVIDENCE REQUIRED",
        "Paper startup and shutdown | **BLOCKED**",
        "No executable paper-runner startup or shutdown command exists on `main`.",
        "Health, heartbeat, and event-loop status | **BLOCKED**",
        "Restart recovery and reconciliation | **BLOCKED**",
        "Stale-data and risk kill switches | **BLOCKED**",
        "Prospective paper acceptance scorecard | **BLOCKED**",
        "Limited-capital launch or abort | **BLOCKED**",
        "`BLOCKED` means there is no operator command to run.",
        "paper_start_authorized = false",
        "limited_capital_authorized = false",
        "account_connectivity = absent",
        "order_submission = absent",
    )
    for text in required_text:
        assert text in documentation

    assert '"allow_paper_promotion": False' in promotion
    assert '"allow_limited_capital": False' in promotion
    assert '"allow_paper_promotion": False' in cross_market
    assert '"allow_limited_capital": False' in cross_market
    assert "_materialize_verified_artifact" in cross_market
    assert "O_NOFOLLOW" in cross_market
    assert "source artifact manifest changed during semantic reconstruction" in cross_market
    assert "workflow_dispatch:" in workflow
    assert "push:" in workflow
    assert "branches: [main]" in workflow
    assert "contents: read" in workflow
    assert "persist-credentials: false" in workflow

    stale_text = (
        "Until that release train reaches `main`",
        "operator acceptance remains **BLOCKED** even when an earlier workflow exited",
        "G0 artifact build therefore does not authorize paper execution",
        "## Executed verification command",
    )
    for text in stale_text:
        assert text not in documentation

    forbidden_live_instructions = (
        "OKX_API_KEY",
        "OKX_SECRET_KEY",
        "--enable-live",
        "--submit-order",
    )
    for text in forbidden_live_instructions:
        assert text not in documentation
