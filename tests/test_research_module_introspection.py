from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path


def _run_isolated_script(script: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_lazy_legacy_report_writer_is_visible_to_module_introspection() -> None:
    package_root = Path(__file__).parents[1] / "src" / "gpt_quant"
    script = textwrap.dedent(
        f"""
        import importlib
        import sys
        import types

        package = types.ModuleType("gpt_quant")
        package.__path__ = [{str(package_root)!r}]
        sys.modules["gpt_quant"] = package

        research = importlib.import_module("gpt_quant.research")
        assert "gpt_quant.research_report" not in sys.modules

        names = dir(research)
        assert names == sorted(set(names))
        assert "write_research_report" in names
        assert "gpt_quant.research_report" not in sys.modules

        legacy_writer = getattr(research, "write_research_report")
        report_module = sys.modules["gpt_quant.research_report"]
        assert legacy_writer is report_module.write_research_report
        """
    )

    _run_isolated_script(script)


def test_star_import_preserves_supported_research_exports() -> None:
    package_root = Path(__file__).parents[1] / "src" / "gpt_quant"
    script = textwrap.dedent(
        f"""
        import sys
        import types

        package = types.ModuleType("gpt_quant")
        package.__path__ = [{str(package_root)!r}]
        sys.modules["gpt_quant"] = package

        namespace = {{}}
        exec("from gpt_quant.research import *", namespace)

        report_module = sys.modules["gpt_quant.research_report"]
        assert namespace["write_research_report"] is report_module.write_research_report
        assert namespace["ResearchResult"].__module__ == "gpt_quant.research"
        assert namespace["run_holdout_research"].__module__ == "gpt_quant.research"
        """
    )

    _run_isolated_script(script)
