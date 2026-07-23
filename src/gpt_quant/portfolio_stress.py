from __future__ import annotations

import json
import math
import os
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass
from numbers import Real
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Any

import numpy as np
import pandas as pd

from ._atomic_publish import publish_staged_paths_atomically
from .portfolio import (
    PortfolioRiskResult,
    _validate_result_against_verified_sources,
    validate_portfolio_provenance,
    write_portfolio_risk_report,
)

_STRESS_CORRELATION_FILENAME = "portfolio_stress_correlation.json"
_PORTFOLIO_BUNDLE_FILENAMES = {
    "json": "portfolio_risk.json",
    "returns": "portfolio_returns.csv",
    "markdown": "portfolio_risk.md",
    "stress_correlation": _STRESS_CORRELATION_FILENAME,
}


@dataclass(frozen=True, slots=True)
class PortfolioStressCorrelationDiagnostic:
    generated_at_utc: str
    report_only: bool
    gate_status: str
    method: dict[str, Any]
    data_summary: dict[str, Any]
    pairwise_results: list[dict[str, Any]]
    maximum_correlation_change: float | None
    maximum_change_pair: list[str] | None
    source_risk_status: str
    source_provenance: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(
            {
                "generated_at_utc": self.generated_at_utc,
                "report_only": self.report_only,
                "gate_status": self.gate_status,
                "method": self.method,
                "data_summary": self.data_summary,
                "pairwise_results": self.pairwise_results,
                "maximum_correlation_change": self.maximum_correlation_change,
                "maximum_change_pair": self.maximum_change_pair,
                "source_risk_status": self.source_risk_status,
                "source_provenance": self.source_provenance,
            }
        )


def _finite_float_or_none(value: object) -> float | None:
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _validate_method(
    *,
    stress_fraction: float,
    minimum_stress_observations: int,
    total_observations: int,
) -> int:
    if (
        isinstance(stress_fraction, bool)
        or not isinstance(stress_fraction, Real)
        or not math.isfinite(float(stress_fraction))
        or not 0.0 < float(stress_fraction) <= 0.5
    ):
        raise ValueError("stress_fraction must be a finite real number in (0, 0.5]")
    if (
        isinstance(minimum_stress_observations, bool)
        or not isinstance(minimum_stress_observations, int)
        or minimum_stress_observations < 4
    ):
        raise ValueError("minimum_stress_observations must be an integer of at least 4")

    stress_observations = max(
        minimum_stress_observations,
        math.ceil(total_observations * float(stress_fraction)),
    )
    if stress_observations >= total_observations:
        raise ValueError("stress subset must be smaller than the full return window")
    return stress_observations


def build_portfolio_stress_correlation_diagnostic(
    result: PortfolioRiskResult,
    *,
    stress_fraction: float = 0.20,
    minimum_stress_observations: int = 5,
) -> PortfolioStressCorrelationDiagnostic:
    """Compare full-window and worst-portfolio-session sleeve correlations without gating."""

    if not isinstance(result, PortfolioRiskResult):
        raise TypeError("result must be a PortfolioRiskResult")
    sleeves = result.data_summary.get("sleeves")
    if not isinstance(sleeves, list) or len(sleeves) < 2:
        raise ValueError("portfolio result must declare at least two sleeve names")
    if not all(isinstance(name, str) and name for name in sleeves):
        raise ValueError("portfolio sleeve names must be non-empty strings")

    return_columns = {name: f"{name}_return" for name in sleeves}
    required_columns = {"strategy_return", *return_columns.values()}
    missing_columns = required_columns - set(result.frame)
    if missing_columns:
        raise ValueError(
            f"portfolio frame is missing stress-correlation columns: {sorted(missing_columns)}"
        )

    total_observations = len(result.frame)
    stress_observations = _validate_method(
        stress_fraction=stress_fraction,
        minimum_stress_observations=minimum_stress_observations,
        total_observations=total_observations,
    )

    sleeve_returns = result.frame[list(return_columns.values())].copy()
    sleeve_returns.columns = sleeves
    values = sleeve_returns.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("portfolio sleeve returns must be finite for stress correlation")

    portfolio_returns = pd.to_numeric(result.frame["strategy_return"], errors="coerce")
    if portfolio_returns.isna().any() or not np.isfinite(portfolio_returns.to_numpy()).all():
        raise ValueError("portfolio returns must be finite for stress correlation")

    ranked = portfolio_returns.sort_values(kind="mergesort")
    stress_index = ranked.index[:stress_observations]
    full_correlation = sleeve_returns.corr()
    stress_correlation = sleeve_returns.loc[stress_index].corr()

    pairwise_results: list[dict[str, Any]] = []
    finite_changes: list[tuple[list[str], float]] = []
    for row_index, left in enumerate(sleeves):
        for right in sleeves[row_index + 1 :]:
            full_value = _finite_float_or_none(full_correlation.loc[left, right])
            stress_value = _finite_float_or_none(stress_correlation.loc[left, right])
            change = (
                stress_value - full_value
                if full_value is not None and stress_value is not None
                else None
            )
            pair = [left, right]
            pairwise_results.append(
                {
                    "pair": pair,
                    "full_window_correlation": full_value,
                    "stress_window_correlation": stress_value,
                    "stress_minus_full_correlation": change,
                }
            )
            if change is not None:
                finite_changes.append((pair, change))

    if finite_changes:
        maximum_change_pair, maximum_correlation_change = max(
            finite_changes,
            key=lambda item: item[1],
        )
    else:
        maximum_change_pair = None
        maximum_correlation_change = None

    provenance = result.data_summary.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("portfolio result must contain validated provenance")

    return PortfolioStressCorrelationDiagnostic(
        generated_at_utc=result.generated_at_utc,
        report_only=True,
        gate_status="not_evaluated",
        method={
            "selection": "lowest portfolio strategy-return observations",
            "tie_break": "stable chronological order",
            "stress_fraction": float(stress_fraction),
            "minimum_stress_observations": minimum_stress_observations,
            "threshold": None,
            "interpretation": (
                "development-market diagnostic only; not used for selection or pass/reject"
            ),
        },
        data_summary={
            "full_window_observations": total_observations,
            "stress_window_observations": stress_observations,
            "stress_window_cutoff_return": float(ranked.iloc[stress_observations - 1]),
            "stress_timestamps": [timestamp.isoformat() for timestamp in stress_index],
            "sleeves": list(sleeves),
        },
        pairwise_results=pairwise_results,
        maximum_correlation_change=maximum_correlation_change,
        maximum_change_pair=maximum_change_pair,
        source_risk_status=result.risk_status,
        source_provenance=deepcopy(provenance),
    )


def write_portfolio_stress_correlation_report(
    result: PortfolioRiskResult,
    output_dir: str | Path,
    *,
    stress_fraction: float = 0.20,
    minimum_stress_observations: int = 5,
) -> Path:
    """Revalidate verified sources and persist the requested report-only diagnostic."""

    if not isinstance(result, PortfolioRiskResult):
        raise TypeError("result must be a PortfolioRiskResult")
    sleeves = result.data_summary.get("sleeves")
    if not isinstance(sleeves, list):
        raise ValueError("portfolio result must declare its sleeve names")
    validate_portfolio_provenance(
        result.data_summary.get("provenance"),
        expected_sleeves=sleeves,
    )
    _validate_result_against_verified_sources(result)
    diagnostic = build_portfolio_stress_correlation_diagnostic(
        result,
        stress_fraction=stress_fraction,
        minimum_stress_observations=minimum_stress_observations,
    )

    output = Path(output_dir)
    output_preexisted = output.exists()
    output.mkdir(parents=True, exist_ok=True)
    destination = output / _STRESS_CORRELATION_FILENAME
    payload = (
        json.dumps(
            diagnostic.to_dict(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")

    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="wb",
            prefix=f".{_STRESS_CORRELATION_FILENAME}.",
            suffix=".tmp",
            dir=output,
            delete=False,
        ) as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, destination)
    except BaseException:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        if not output_preexisted:
            with suppress(OSError):
                output.rmdir()
        raise
    return destination


def write_portfolio_risk_bundle(
    result: PortfolioRiskResult,
    output_dir: str | Path,
    *,
    stress_fraction: float = 0.20,
    minimum_stress_observations: int = 5,
) -> dict[str, Path]:
    """Publish the core report and requested stress diagnostic as one generation."""

    if not isinstance(result, PortfolioRiskResult):
        raise TypeError("result must be a PortfolioRiskResult")

    output = Path(output_dir)
    destinations = {
        name: output / filename for name, filename in _PORTFOLIO_BUNDLE_FILENAMES.items()
    }

    def stage_bundle(staging: Path) -> dict[str, Path]:
        staged_paths = write_portfolio_risk_report(result, staging)
        staged_paths["stress_correlation"] = write_portfolio_stress_correlation_report(
            result,
            staging,
            stress_fraction=stress_fraction,
            minimum_stress_observations=minimum_stress_observations,
        )
        if set(staged_paths) != set(destinations):
            raise ValueError("portfolio bundle must exactly match the report file set")
        return staged_paths

    return publish_staged_paths_atomically(
        output,
        destinations,
        stage_paths=stage_bundle,
        commit_order=tuple(_PORTFOLIO_BUNDLE_FILENAMES),
        staging_prefix=".portfolio-risk-bundle-",
        error_label="portfolio bundle",
    )
