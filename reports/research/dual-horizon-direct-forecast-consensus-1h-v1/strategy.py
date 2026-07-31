"""Frozen dual-horizon direct forecast consensus state machine."""

from __future__ import annotations

from typing import Any

import numpy as np
from common import (
    FEE,
    HORIZONS,
    TRAIN_WINDOW_HOURS,
    build_feature_matrix,
    future_labels,
    robust_ridge_predict,
)


def build_signals(market: dict[str, Any]) -> dict[str, Any]:
    timestamps = market["timestamps"]
    closes = market["closes"]
    opens = market["opens"]
    n = len(closes)
    features = build_feature_matrix(market)
    labels = {h: future_labels(opens, h) for h in HORIZONS}

    base = np.zeros(n, dtype=np.int8)
    base[2_160:] = (closes[2_160:] > closes[:-2_160]).astype(np.int8)
    b1 = np.zeros(n, dtype=np.int8)
    candidate = np.zeros(n, dtype=np.int8)
    predictions = {h: np.full(n, np.nan) for h in HORIZONS}
    training_rows = {h: np.zeros(n, dtype=np.int32) for h in HORIZONS}
    fit_status = {h: np.zeros(n, dtype=np.int8) for h in HORIZONS}
    decision_mask = np.zeros(n, dtype=bool)
    current_b1 = 0
    current_candidate = 0
    label_boundary_violations = 0

    daily_indices = np.flatnonzero(timestamps.dt.hour.to_numpy() == 0)
    daily_set = set(int(x) for x in daily_indices)
    for t in range(720, n):
        if timestamps.iloc[t].hour == 0:
            current_b1 = int(base[t])
            decision_mask[t] = True
            start = max(720, t - TRAIN_WINDOW_HOURS)
            eligible_daily = daily_indices[(daily_indices >= start) & (daily_indices < t)]
            okay = True
            for horizon in HORIZONS:
                eligible = eligible_daily[eligible_daily + horizon + 1 <= t]
                if len(eligible) and int(np.max(eligible + horizon + 1)) > t:
                    label_boundary_violations += 1
                prediction, diagnostic = robust_ridge_predict(
                    features, labels[horizon], eligible, t
                )
                predictions[horizon][t] = prediction
                training_rows[horizon][t] = diagnostic["rows"]
                fit_status[horizon][t] = int(diagnostic["status"] == "fit")
                okay = okay and np.isfinite(prediction)
            current_candidate = int(
                okay
                and predictions[24][t] > 0.0
                and predictions[168][t] > 0.0
            )
        b1[t] = current_b1
        candidate[t] = current_candidate

    if label_boundary_violations:
        raise ValueError("future label crossed a decision boundary")
    if not all(int(x) in daily_set for x in np.flatnonzero(decision_mask)):
        raise ValueError("non-daily model decision")

    signals = {"candidate": candidate, "B0": base, "B1": b1}
    paths: dict[str, Any] = {}
    market_return = opens[1:] / opens[:-1] - 1.0
    for name, signal in signals.items():
        position = np.zeros(n - 1, dtype=float)
        position[1:] = signal[:-2]
        changes = np.abs(position - np.r_[0.0, position[:-1]])
        gross = position * market_return
        fee = FEE * changes
        net = gross - fee
        if not np.allclose(net, gross - FEE * changes, atol=0, rtol=0):
            raise ValueError("fee identity failure")
        paths[name] = {
            "signal": signal,
            "position": position,
            "changes": changes,
            "gross": gross,
            "fee": fee,
            "net": net,
        }
    return {
        "paths": paths,
        "features": features,
        "labels": labels,
        "predictions": predictions,
        "training_rows": training_rows,
        "fit_status": fit_status,
        "decision_mask": decision_mask,
    }
