from __future__ import annotations

from typing import Any


def calculate_slo(target: float, bad_events: int, total_events: int) -> dict[str, Any]:
    if not 0 < target < 1:
        raise ValueError("target must be between 0 and 1 (exclusive)")
    if bad_events < 0 or total_events < 0 or bad_events > total_events:
        raise ValueError("invalid event counts")
    allowed_bad_rate = 1.0 - target
    if total_events == 0:
        return {
            "target": target,
            "actual_bad_rate": 0.0,
            "allowed_bad_rate": allowed_bad_rate,
            "burn_rate": 0.0,
            "remaining_error_budget_fraction": 1.0,
            "breached": False,
        }
    actual_bad_rate = bad_events / total_events
    burn_rate = actual_bad_rate / allowed_bad_rate
    consumed_fraction = min(1.0, actual_bad_rate / allowed_bad_rate)
    return {
        "target": target,
        "actual_bad_rate": actual_bad_rate,
        "allowed_bad_rate": allowed_bad_rate,
        "burn_rate": burn_rate,
        "remaining_error_budget_fraction": max(0.0, 1.0 - consumed_fraction),
        "breached": bool(actual_bad_rate > allowed_bad_rate),
    }


def evaluate_multiwindow_burn(
    *,
    short_window_burn: float,
    long_window_burn: float,
    policy: str = "google_sre",
    short_threshold: float = 14.4,
    long_threshold: float = 6.0,
) -> dict[str, Any]:
    """Multi-window burn-rate policy to distinguish sustained burns from transient spikes.

    Policies:
    - ``google_sre``: page only when BOTH windows exceed their threshold.
      A spike that clears before the long window settles does not page.
      severity=critical when short > short_threshold, warning when only long fires.
    - ``strict``: page when EITHER window exceeds its threshold.
      More sensitive — catches slow burns faster but may page on short spikes.
    - ``starter``: never pages (original no-op, kept for backwards compat).

    Args:
        short_window_burn: burn rate over the short window (e.g. 5 min).
        long_window_burn: burn rate over the long window (e.g. 1 hour).
        policy: one of ``google_sre``, ``strict``, ``starter``.
        short_threshold: multiplier threshold for the short window (default 14.4×).
        long_threshold: multiplier threshold for the long window (default 6.0×).
    """
    short_firing = short_window_burn > short_threshold
    long_firing = long_window_burn > long_threshold

    if policy == "starter":
        return {
            "page": False,
            "severity": "info",
            "reason": "starter_policy_not_implemented",
            "short_window_burn": short_window_burn,
            "long_window_burn": long_window_burn,
        }

    if policy == "google_sre":
        # Both windows must fire — guards against transient spikes
        page = short_firing and long_firing
        if page:
            severity = "critical"
            reason = "sustained fast burn: both windows exceeded threshold"
        elif long_firing:
            # Slow sustained burn detected but short window hasn't peaked yet
            severity = "warning"
            reason = "slow burn: long window exceeded threshold"
            page = True
        elif short_firing:
            severity = "info"
            reason = "transient spike: short window fired but long window is normal"
        else:
            severity = "info"
            reason = "burn rate within acceptable range"

    elif policy == "strict":
        # Either window firing is enough to page
        page = short_firing or long_firing
        if short_firing and long_firing:
            severity = "critical"
            reason = "both windows exceeded threshold"
        elif short_firing:
            severity = "warning"
            reason = "short window exceeded threshold"
        elif long_firing:
            severity = "warning"
            reason = "long window exceeded threshold"
        else:
            severity = "info"
            reason = "burn rate within acceptable range"

    else:
        raise ValueError(f"Unsupported policy: {policy!r}. Choose 'google_sre', 'strict', or 'starter'.")

    return {
        "page": bool(page),
        "severity": severity,
        "reason": reason,
        "short_window_burn": short_window_burn,
        "long_window_burn": long_window_burn,
        "short_threshold": short_threshold,
        "long_threshold": long_threshold,
        "policy": policy,
    }
