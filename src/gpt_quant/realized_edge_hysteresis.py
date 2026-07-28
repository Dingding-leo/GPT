from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

ANNUALIZATION = 8_760
FEE_ONE_WAY_BPS = 5.0
INNOVATION_LOOKBACK = 168
MAD_TO_SIGMA = 1.4826
UNCERTAINTY_Z = 1.645
_EPSILON = 1e-12
_REQUIRED_COLUMNS = {
    "timestamp",
    "asset_return",
    "position",
    "turnover",
    "trading_cost",
    "strategy_return",
    "fold",
}


@dataclass(frozen=True, slots=True)
class HysteresisDiagnostics:
    observations: int
    fallback_decisions: int
    suppressed_decisions: int
    revision_opportunities: int

    @property
    def no_trade_frequency(self) -> float:
        return self.suppressed_decisions / self.observations

    @property
    def suppression_rate(self) -> float:
        if self.revision_opportunities == 0:
            return 0.0
        return self.suppressed_decisions / self.revision_opportunities


def _validated_canonical_frame(frame: pd.DataFrame) -> pd.DataFrame:
    missing = _REQUIRED_COLUMNS.difference(frame.columns)
    if missing:
        raise ValueError(f"missing canonical walk-forward columns: {sorted(missing)}")
    if frame.empty:
        raise ValueError("canonical walk-forward frame must not be empty")

    clean = frame.copy()
    timestamps = pd.to_datetime(clean["timestamp"], utc=True, errors="raise")
    if timestamps.duplicated().any() or not timestamps.is_monotonic_increasing:
        raise ValueError("timestamps must be unique and strictly increasing")
    if len(timestamps) > 1:
        step = timestamps.diff().iloc[1:]
        if not bool((step == pd.Timedelta(hours=1)).all()):
            raise ValueError("canonical walk-forward rows must use a continuous 1H grid")
    clean["timestamp"] = timestamps

    numeric_columns = [
        "asset_return",
        "position",
        "turnover",
        "trading_cost",
        "strategy_return",
        "fold",
    ]
    for column in numeric_columns:
        values = pd.to_numeric(clean[column], errors="raise").to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise ValueError(f"{column} must contain only finite values")
        clean[column] = values

    positions = clean["position"].to_numpy(dtype=float)
    if bool((positions < -_EPSILON).any()) or bool((positions > 1.0 + _EPSILON).any()):
        raise ValueError(
            "canonical strategy positions must remain in the long/cash interval [0, 1]"
        )

    expected_turnover = np.empty(len(clean), dtype=float)
    expected_turnover[0] = abs(positions[0])
    expected_turnover[1:] = np.abs(np.diff(positions))
    if not np.allclose(
        clean["turnover"].to_numpy(dtype=float),
        expected_turnover,
        rtol=0.0,
        atol=1e-12,
    ):
        raise ValueError("canonical turnover does not match absolute position adjustments")

    expected_cost = expected_turnover * FEE_ONE_WAY_BPS / 10_000.0
    if not np.allclose(
        clean["trading_cost"].to_numpy(dtype=float),
        expected_cost,
        rtol=0.0,
        atol=1e-12,
    ):
        raise ValueError("canonical trading cost is not exactly 5 bps one-way")

    expected_return = positions * clean["asset_return"].to_numpy(dtype=float) - expected_cost
    if not np.allclose(
        clean["strategy_return"].to_numpy(dtype=float),
        expected_return,
        rtol=0.0,
        atol=1e-12,
    ):
        raise ValueError("canonical strategy return cannot be reconstructed at exactly 5 bps")
    return clean


def apply_target_innovation_hysteresis(
    canonical_frame: pd.DataFrame,
) -> tuple[pd.DataFrame, HysteresisDiagnostics]:
    """Suppress target revisions that do not exceed causal target-innovation uncertainty.

    The input ``position`` is the canonical one-bar-delayed desired exposure for each
    return row. The rule never changes the upstream temporal signal or selector. It only
    decides whether the already-causal desired exposure is sufficiently different from
    the last committed exposure to justify another adjustment.
    """

    clean = _validated_canonical_frame(canonical_frame)
    desired = clean["position"].to_numpy(dtype=float)
    asset_return = clean["asset_return"].to_numpy(dtype=float)
    observations = len(clean)

    innovations = np.empty(observations, dtype=float)
    innovations[0] = np.nan
    innovations[1:] = np.diff(desired)

    committed = np.empty(observations, dtype=float)
    band = np.full(observations, np.nan, dtype=float)
    fallback = np.zeros(observations, dtype=bool)
    suppressed = np.zeros(observations, dtype=bool)
    revision_opportunity = np.zeros(observations, dtype=bool)

    previous_committed = 0.0
    for offset in range(observations):
        proposed_change = abs(desired[offset] - previous_committed)
        revision_opportunity[offset] = proposed_change > _EPSILON

        if offset < INNOVATION_LOOKBACK + 1:
            fallback[offset] = True
            next_committed = desired[offset]
        else:
            history = innovations[offset - INNOVATION_LOOKBACK : offset]
            if len(history) != INNOVATION_LOOKBACK or not np.isfinite(history).all():
                fallback[offset] = True
                next_committed = desired[offset]
            else:
                center = float(np.median(history))
                mad = float(np.median(np.abs(history - center)))
                band[offset] = UNCERTAINTY_Z * MAD_TO_SIGMA * mad
                if proposed_change > band[offset]:
                    next_committed = desired[offset]
                else:
                    next_committed = previous_committed
                    suppressed[offset] = proposed_change > _EPSILON

        committed[offset] = next_committed
        previous_committed = next_committed

    turnover = np.empty(observations, dtype=float)
    turnover[0] = abs(committed[0])
    turnover[1:] = np.abs(np.diff(committed))
    trading_cost = turnover * FEE_ONE_WAY_BPS / 10_000.0
    gross_return = committed * asset_return
    strategy_return = gross_return - trading_cost

    result = clean.copy()
    result["hysteresis_position"] = committed
    result["hysteresis_turnover"] = turnover
    result["hysteresis_trading_cost"] = trading_cost
    result["hysteresis_gross_strategy_return"] = gross_return
    result["hysteresis_strategy_return"] = strategy_return
    result["hysteresis_band"] = band
    result["hysteresis_fallback"] = fallback
    result["hysteresis_suppressed"] = suppressed

    diagnostics = HysteresisDiagnostics(
        observations=observations,
        fallback_decisions=int(fallback.sum()),
        suppressed_decisions=int(suppressed.sum()),
        revision_opportunities=int(revision_opportunity.sum()),
    )
    return result, diagnostics
