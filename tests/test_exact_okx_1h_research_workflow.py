from pathlib import Path


def test_canonical_intraday_workflow_uses_exact_byte_replay_before_promotion() -> None:
    workflow = (
        Path(__file__).parents[1] / ".github" / "workflows" / "intraday-1h-research.yml"
    ).read_text(encoding="utf-8")

    exact_runner = "python scripts/run_exact_okx_1h_research.py"
    provenance_gate = "python -m gpt_quant.intraday_1h_source_provenance"
    promotion_gate = "python scripts/build_intraday_1h_promotion_gate.py"
    manifest_gate = "python -m gpt_quant.artifact_manifest"

    assert exact_runner in workflow
    assert "python scripts/run_okx_research.py" not in workflow
    assert provenance_gate in workflow
    assert "--verify-only" in workflow
    assert workflow.index(exact_runner) < workflow.index(provenance_gate)
    assert workflow.index(provenance_gate) < workflow.index(promotion_gate)
    assert workflow.index(provenance_gate) < workflow.index(manifest_gate)
    assert 'test -s "$report_dir/intraday-1h-source-provenance.json"' in workflow
