#!/usr/bin/env python3
"""Great Expectations Core 1.21 — Suite + ValidationDefinition + Checkpoint + Actions."""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import great_expectations as gx
except ImportError as exc:
    raise SystemExit("great_expectations is not installed. Run: pip install -r requirements.txt") from exc

from src.contract_validator import load_contract

QUARANTINE_DIR = ROOT / "data" / "quarantine"


def build_expectations(contract: dict[str, Any]) -> list[Any]:
    """Build GX expectation list from contract definition, preserving severity in meta."""
    expectations = []
    columns = contract.get("columns", {})

    for col, rules in columns.items():
        sev = rules.get("severity", "warning")
        meta = {"severity": sev}

        if rules.get("required"):
            expectations.append(
                gx.expectations.ExpectColumnValuesToNotBeNull(column=col, meta=meta)
            )

        if rules.get("unique"):
            expectations.append(
                gx.expectations.ExpectColumnValuesToBeUnique(column=col, meta=meta)
            )

        if "accepted_values" in rules:
            expectations.append(
                gx.expectations.ExpectColumnValuesToBeInSet(
                    column=col, value_set=rules["accepted_values"], meta=meta
                )
            )

        if "min" in rules or "max" in rules:
            expectations.append(
                gx.expectations.ExpectColumnValuesToBeBetween(
                    column=col,
                    min_value=rules.get("min"),
                    max_value=rules.get("max"),
                    meta=meta,
                )
            )

    return expectations


def build_suite(context: Any, contract: dict[str, Any]) -> Any:
    suite = gx.ExpectationSuite(name="orders_suite")
    for exp in build_expectations(contract):
        suite.add_expectation(exp)
    return context.suites.add(suite)


def parse_failures(checkpoint_result: Any) -> list[dict[str, Any]]:
    """Extract failed expectations with severity from checkpoint result."""
    failures = []
    for val_result in checkpoint_result.run_results.values():
        results = getattr(val_result, "results", None) or val_result.get("results", [])
        for er in results:
            success = getattr(er, "success", None)
            if success is None:
                success = er.get("success", True)
            if not success:
                cfg = getattr(er, "expectation_config", None) or er.get("expectation_config", {})
                exp_type = getattr(cfg, "type", None) or cfg.get("type", "unknown")
                exp_meta = getattr(cfg, "meta", None) or cfg.get("meta", {})
                sev = exp_meta.get("severity", "warning") if isinstance(exp_meta, dict) else "warning"
                failures.append({"expectation": exp_type, "severity": sev})
    return failures


def apply_gx_actions(
    failures: list[dict[str, Any]],
    source_path: Path | None = None,
) -> dict[str, Any]:
    """Block on critical, quarantine on warning, pass otherwise."""
    critical = [f for f in failures if f["severity"] == "critical"]
    warnings = [f for f in failures if f["severity"] == "warning"]

    if critical:
        return {
            "action": "blocked",
            "reason": f"{len(critical)} critical failure(s)",
            "failures": failures,
        }

    if warnings and source_path and source_path.exists():
        QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
        dest = QUARANTINE_DIR / source_path.name
        shutil.copy2(source_path, dest)
        meta = {
            "quarantined_at": datetime.now(timezone.utc).isoformat(),
            "source": str(source_path),
            "warnings": warnings,
        }
        (QUARANTINE_DIR / (source_path.stem + "_meta.json")).write_text(
            json.dumps(meta, indent=2)
        )
        return {"action": "quarantined", "quarantine_path": str(dest), "failures": failures}

    return {"action": "passed", "failures": failures}


def run_gx_validation(df: pd.DataFrame, contract: dict[str, Any], source_path: Path | None = None) -> dict[str, Any]:
    """Full GX Suite → ValidationDefinition → Checkpoint → Actions pipeline."""
    context = gx.get_context(mode="ephemeral")

    ds = context.data_sources.add_pandas("orders_pandas")
    asset = ds.add_dataframe_asset("orders_dataframe")
    batch_def = asset.add_batch_definition_whole_dataframe("whole_orders")

    suite = build_suite(context, contract)

    val_def = context.validation_definitions.add(
        gx.ValidationDefinition(name="orders_validation", data=batch_def, suite=suite)
    )

    checkpoint = context.checkpoints.add(
        gx.Checkpoint(name="orders_checkpoint", validation_definitions=[val_def])
    )

    result = checkpoint.run(batch_parameters={"dataframe": df})
    failures = parse_failures(result)
    action = apply_gx_actions(failures, source_path)

    return {
        "success": bool(result.success),
        **action,
    }


def main() -> None:
    source_path = ROOT / "data" / "incoming" / "orders.csv"
    df = pd.read_csv(source_path)
    contract = load_contract(ROOT / "contracts" / "orders_contract.yaml")

    result = run_gx_validation(df, contract, source_path)

    print("\n=== GX Checkpoint Result ===")
    print(f"Overall success : {result['success']}")
    print(f"Action          : {result['action'].upper()}")

    failures = result.get("failures", [])
    if failures:
        print(f"\nFailures ({len(failures)}):")
        for f in failures:
            print(f"  [{f['severity'].upper()}] {f['expectation']}")
    else:
        print("\nAll expectations PASSED")

    if result["action"] == "blocked":
        print(f"\nDATA BLOCKED: {result['reason']}")
        sys.exit(1)
    elif result["action"] == "quarantined":
        print(f"\nDATA QUARANTINED → {result['quarantine_path']}")


if __name__ == "__main__":
    main()
