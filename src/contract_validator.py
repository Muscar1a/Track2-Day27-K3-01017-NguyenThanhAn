"""Contract validator with type, freshness, and action support."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


class DataBlockedError(Exception):
    """Raised when critical contract violations are detected."""


def _issue(
    check: str,
    *,
    column: str | None,
    severity: str,
    passed: bool,
    details: str,
) -> dict[str, Any]:
    return {
        "check": check,
        "column": column,
        "severity": severity,
        "passed": bool(passed),
        "details": details,
    }


def load_contract(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _validate_type(
    series: pd.Series, expected_type: str, column: str, severity: str
) -> dict[str, Any] | None:
    if expected_type == "integer":
        numeric = pd.to_numeric(series, errors="coerce")
        not_numeric = numeric.isna() & series.notna()
        not_int = numeric.notna() & (numeric % 1 != 0)
        invalid_count = int((not_numeric | not_int).sum())
    elif expected_type == "number":
        numeric = pd.to_numeric(series, errors="coerce")
        invalid_count = int((numeric.isna() & series.notna()).sum())
    elif expected_type == "datetime":
        parsed = pd.to_datetime(series, errors="coerce", utc=True)
        invalid_count = int((parsed.isna() & series.notna()).sum())
    elif expected_type == "string":
        invalid_count = 0
    else:
        return None
    return _issue(
        "type",
        column=column,
        severity=severity,
        passed=(invalid_count == 0),
        details=f"expected_type={expected_type}, invalid_count={invalid_count}",
    )


def _validate_freshness(df: pd.DataFrame, freshness_config: dict[str, Any]) -> dict[str, Any]:
    """Compare freshness column against a reference timestamp within the data.

    Reference = max(created_at) if present, else min(freshness_col).
    delay = ref - max(freshness_col). Negative delay means data is being
    updated after creation (healthy). Large positive delay means updates lag.
    """
    col = freshness_config.get("column")
    max_delay = freshness_config.get("max_delay_minutes", 30)
    severity = freshness_config.get("severity", "warning")

    if col not in df.columns:
        return _issue(
            "freshness", column=col, severity=severity, passed=False,
            details=f"freshness column '{col}' not found in dataframe",
        )

    parsed = pd.to_datetime(df[col], errors="coerce", utc=True)
    if parsed.isna().all():
        return _issue(
            "freshness", column=col, severity=severity, passed=False,
            details="all values in freshness column are unparseable",
        )

    max_updated = parsed.max()

    if "created_at" in df.columns:
        ref = pd.to_datetime(df["created_at"], errors="coerce", utc=True).max()
        ref_label = "max(created_at)"
    else:
        ref = parsed.min()
        ref_label = f"min({col})"

    delay_minutes = (ref - max_updated).total_seconds() / 60.0
    passed = delay_minutes <= max_delay

    return _issue(
        "freshness",
        column=col,
        severity=severity,
        passed=passed,
        details=(
            f"delay_minutes={delay_minutes:.1f}, "
            f"max_delay_minutes={max_delay}, "
            f"ref={ref_label}"
        ),
    )


def validate_dataframe(df: pd.DataFrame, contract: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    columns = contract.get("columns", {})

    for column, rules in columns.items():
        severity = rules.get("severity", "warning")
        required = bool(rules.get("required", False))

        if column not in df.columns:
            if required:
                issues.append(
                    _issue(
                        "required_column",
                        column=column,
                        severity=severity,
                        passed=False,
                        details=f"Missing required column: {column}",
                    )
                )
            continue

        series = df[column]

        if required:
            null_count = int(series.isna().sum())
            issues.append(
                _issue(
                    "not_null",
                    column=column,
                    severity=severity,
                    passed=(null_count == 0),
                    details=f"null_count={null_count}",
                )
            )

        if rules.get("unique"):
            duplicate_count = int(series.duplicated(keep=False).sum())
            issues.append(
                _issue(
                    "unique",
                    column=column,
                    severity=severity,
                    passed=(duplicate_count == 0),
                    details=f"duplicate_rows={duplicate_count}",
                )
            )

        accepted = rules.get("accepted_values")
        if accepted is not None:
            invalid_mask = series.notna() & ~series.isin(accepted)
            invalid_count = int(invalid_mask.sum())
            issues.append(
                _issue(
                    "accepted_values",
                    column=column,
                    severity=severity,
                    passed=(invalid_count == 0),
                    details=f"invalid_count={invalid_count}; accepted={accepted}",
                )
            )

        if "min" in rules or "max" in rules:
            numeric = pd.to_numeric(series, errors="coerce")
            invalid = pd.Series(False, index=series.index)
            if "min" in rules:
                invalid |= numeric < rules["min"]
            if "max" in rules:
                invalid |= numeric > rules["max"]
            invalid_count = int(invalid.fillna(False).sum())
            issues.append(
                _issue(
                    "range",
                    column=column,
                    severity=severity,
                    passed=(invalid_count == 0),
                    details=f"invalid_count={invalid_count}",
                )
            )

        col_type = rules.get("type")
        if col_type:
            result = _validate_type(series, col_type, column, severity)
            if result is not None:
                issues.append(result)

    freshness_config = contract.get("freshness")
    if freshness_config:
        issues.append(_validate_freshness(df, freshness_config))

    return issues


def failed_issues(issues: list[dict[str, Any]], min_severity: str | None = None) -> list[dict[str, Any]]:
    failed = [i for i in issues if not i.get("passed", False)]
    if min_severity is None:
        return failed
    order = {"info": 0, "warning": 1, "critical": 2}
    threshold = order[min_severity]
    return [i for i in failed if order.get(i.get("severity", "warning"), 1) >= threshold]


def apply_action(
    issues: list[dict[str, Any]],
    source_path: str | Path | None = None,
) -> dict[str, Any]:
    """Apply block/quarantine/warn based on issue severity.

    critical failures → raise DataBlockedError (pipeline stops).
    warning failures  → copy file to data/quarantine/ + write metadata JSON.
    info/no failures  → warn only, pipeline continues.
    """
    failed = [i for i in issues if not i.get("passed", True)]
    critical = [i for i in failed if i.get("severity") == "critical"]
    warnings = [i for i in failed if i.get("severity") == "warning"]

    if critical:
        raise DataBlockedError(
            f"{len(critical)} critical issue(s): "
            + ", ".join(f"{i['check']}({i['column']})" for i in critical)
        )

    if warnings and source_path is not None:
        src = Path(source_path)
        if src.exists():
            quarantine_dir = src.parent.parent / "quarantine"
            quarantine_dir.mkdir(parents=True, exist_ok=True)
            dest = quarantine_dir / src.name
            shutil.copy2(src, dest)
            meta = {
                "quarantined_at": datetime.now(timezone.utc).isoformat(),
                "source": str(src),
                "warnings": [
                    {"check": i["check"], "column": i["column"], "details": i["details"]}
                    for i in warnings
                ],
            }
            (quarantine_dir / (src.stem + "_meta.json")).write_text(
                json.dumps(meta, indent=2)
            )
            return {"action": "quarantined", "quarantine_path": str(dest), "issues": failed}

    if failed:
        return {"action": "warned", "issues": failed}

    return {"action": "passed", "issues": []}
