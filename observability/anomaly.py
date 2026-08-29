"""Anomaly detection starter.

Z-score is deliberately the default baseline. Students should improve `auto`
mode for seasonality/outliers rather than deleting the simple implementation.
"""
from __future__ import annotations

from typing import Any, Iterable

import numpy as np


def zscore_detector(current: float, history: Iterable[float], threshold: float = 3.0) -> dict[str, Any]:
    values = np.asarray(list(history), dtype=float)
    if values.size < 3:
        return {"is_anomaly": False, "score": 0.0, "method": "zscore", "reason": "insufficient_history"}
    mean = float(np.mean(values))
    std = float(np.std(values))
    if std == 0:
        score = float("inf") if float(current) != mean else 0.0
    else:
        score = abs(float(current) - mean) / std
    return {
        "is_anomaly": bool(score > threshold),
        "score": float(score),
        "method": "zscore",
        "reason": f"mean={mean:.3f}, std={std:.3f}, threshold={threshold}",
    }


def mad_detector(current: float, history: Iterable[float], threshold: float = 3.5) -> dict[str, Any]:
    """Median Absolute Deviation detector — robust against outliers in history."""
    values = np.asarray(list(history), dtype=float)
    if values.size < 5:
        return {"is_anomaly": False, "score": 0.0, "method": "mad", "reason": "insufficient_history"}
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    if mad == 0:
        # All history values identical: any deviation is a definite anomaly.
        score = float("inf") if float(current) != median else 0.0
        return {
            "is_anomaly": bool(score > 0),
            "score": score,
            "method": "mad",
            "reason": f"median={median:.3f}, mad=0 (constant history), threshold={threshold}",
        }
    modified_z = 0.6745 * abs(float(current) - median) / mad
    return {
        "is_anomaly": bool(modified_z > threshold),
        "score": float(modified_z),
        "method": "mad",
        "reason": f"median={median:.3f}, mad={mad:.3f}, threshold={threshold}",
    }


def _same_weekday_detector(
    current: float, same_weekday_history: list[float], threshold: float = 3.5
) -> dict[str, Any]:
    """Compare current value against same-day-of-week history to handle seasonality."""
    values = np.asarray(same_weekday_history, dtype=float)
    if values.size < 3:
        return {"is_anomaly": False, "score": 0.0, "method": "auto:same_weekday", "reason": "insufficient_same_weekday_history"}
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    if mad == 0:
        score = float("inf") if float(current) != median else 0.0
        return {
            "is_anomaly": bool(score > 0),
            "score": score,
            "method": "auto:same_weekday",
            "reason": f"same_weekday median={median:.3f}, mad=0 (constant)",
        }
    modified_z = 0.6745 * abs(float(current) - median) / mad
    return {
        "is_anomaly": bool(modified_z > threshold),
        "score": float(modified_z),
        "method": "auto:same_weekday",
        "reason": f"same_weekday median={median:.3f}, mad={mad:.3f}, threshold={threshold}",
    }


def detect_anomaly(
    current: float,
    history: Iterable[float],
    *,
    method: str = "auto",
    threshold: float = 3.0,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Detect whether `current` is anomalous given `history`.

    Methods:
    - ``zscore``: basic z-score.
    - ``mad``: Median Absolute Deviation (robust against history outliers).
    - ``auto``: context-aware layered selection:
        1. same-weekday MAD if ``context["same_weekday_history"]`` has ≥3 pts
        2. MAD if ``context["same_segment_history"]`` has ≥5 pts, or full history ≥5 pts
        3. z-score fallback

    Context keys:
    - ``same_weekday_history``: list[float] — history for the same day of week
    - ``same_segment_history``: list[float] — history for the same cohort/segment
    - ``known_event``: bool — raise threshold by 1.5× to reduce false positives
    - ``metric_name``: str — informational, logged in reason
    """
    if method == "mad":
        return mad_detector(current, history)
    if method == "zscore":
        return zscore_detector(current, history, threshold=threshold)

    if method == "auto":
        ctx = context or {}

        # known_event: expected spike/drop — raise threshold to reduce false positives
        effective_threshold = threshold * 1.5 if ctx.get("known_event") else threshold

        # Layer 1: same-weekday baseline (handles seasonality)
        same_weekday = ctx.get("same_weekday_history") or []
        if len(same_weekday) >= 3:
            result = _same_weekday_detector(current, same_weekday, threshold=effective_threshold)
            if ctx.get("known_event"):
                result["reason"] += "; known_event=true, threshold raised"
            return result

        # Layer 2: MAD on segment history or full history (handles outliers in baseline)
        segment_history = ctx.get("same_segment_history") or list(history)
        if len(segment_history) >= 5:
            result = mad_detector(current, segment_history, threshold=effective_threshold)
            result["method"] = "auto:mad"
            if ctx.get("known_event"):
                result["reason"] += "; known_event=true, threshold raised"
            return result

        # Layer 3: z-score fallback
        result = zscore_detector(current, history, threshold=effective_threshold)
        result["method"] = "auto:zscore"
        if ctx.get("known_event"):
            result["reason"] += "; known_event=true, threshold raised"
        return result

    raise ValueError(f"Unsupported method: {method}")
