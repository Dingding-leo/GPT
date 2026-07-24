from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

import pytest

from gpt_quant.walk_forward import _score as canonical_selection_score

_REPO_ROOT = Path(__file__).parents[1]
_REPORT_DIR = _REPO_ROOT / "reports" / "research" / "fold_local_top3_score_ensemble"
_PACKAGE_NAME = "fold_local_top3_score_ensemble_score_binding"
_PACKAGE_SPEC = importlib.util.spec_from_file_location(
    _PACKAGE_NAME,
    _REPORT_DIR / "__init__.py",
    submodule_search_locations=[str(_REPORT_DIR)],
)
if _PACKAGE_SPEC is None or _PACKAGE_SPEC.loader is None:
    raise RuntimeError(f"unable to import research package from {_REPORT_DIR}")
_package = importlib.util.module_from_spec(_PACKAGE_SPEC)
sys.modules[_PACKAGE_NAME] = _package
_PACKAGE_SPEC.loader.exec_module(_package)
stats = importlib.import_module(f"{_PACKAGE_NAME}.stats")


@pytest.mark.parametrize(
    "metrics",
    [
        {
            "sharpe": 0.6548735577594222,
            "calmar": 0.45247103379724823,
            "max_drawdown": -0.29023428558066644,
            "annualized_turnover": 14.321919517629233,
        },
        {
            "sharpe": -0.25,
            "calmar": -0.10,
            "max_drawdown": -0.65,
            "annualized_turnover": 30.0,
        },
        {
            "sharpe": 1.25,
            "calmar": 1.75,
            "max_drawdown": -0.12,
            "annualized_turnover": 2.5,
        },
    ],
)
def test_reimplemented_selection_score_matches_canonical_score(
    metrics: dict[str, float],
) -> None:
    assert stats.selection_score(metrics) == pytest.approx(canonical_selection_score(metrics))
