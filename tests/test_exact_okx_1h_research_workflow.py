from pathlib import Path


def test_canonical_intraday_workflow_replays_exact_source_before_promotion() -> None:
    workflow = (
        Path(__file__).parents[1] / ".github" / "workflows" / "intraday-1h-research.yml"
    ).read_text(encoding="utf-8")

    acquisition = "python scripts/run_okx_1h_coverage.py"
    research = "python scripts/run_okx_research.py"
    snapshot_input = '--snapshot-dir "$SOURCE_ROOT/${{ matrix.inst_id }}/snapshot"'
    provenance_gate = "python -m gpt_quant.intraday_1h_source_provenance"
    promotion_gate = "python scripts/build_intraday_1h_promotion_gate.py"
    manifest_gate = "python -m gpt_quant.artifact_manifest"

    assert acquisition in workflow
    assert research in workflow
    assert snapshot_input in workflow
    assert provenance_gate in workflow
    assert workflow.index(acquisition) < workflow.index(research)
    assert workflow.index(research) < workflow.index(provenance_gate)
    assert workflow.index(provenance_gate) < workflow.index(promotion_gate)
    assert workflow.index(provenance_gate) < workflow.index(manifest_gate)
    assert 'test -s "$REPORT_DIR/intraday-1h-source-provenance.json"' in workflow
