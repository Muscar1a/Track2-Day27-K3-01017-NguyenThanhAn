from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any


def load_graph(path: str | Path) -> dict[str, list[str]]:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return payload["dataset_lineage"] if "dataset_lineage" in payload else payload


def get_downstream_assets(graph: dict[str, list[str]], start: str) -> list[str]:
    """Return transitive downstream assets in BFS order, excluding start."""
    seen = {start}
    q: deque[str] = deque([start])
    out: list[str] = []
    while q:
        node = q.popleft()
        for child in graph.get(node, []):
            if child not in seen:
                seen.add(child)
                out.append(child)
                q.append(child)
    return out


def get_column_downstream(
    column_graph: dict[str, list[str]], start_column: str
) -> list[str]:
    """Return all transitive downstream columns in BFS order, excluding start."""
    seen = {start_column}
    q: deque[str] = deque([start_column])
    out: list[str] = []
    while q:
        node = q.popleft()
        for child in column_graph.get(node, []):
            if child not in seen:
                seen.add(child)
                out.append(child)
                q.append(child)
    return out


def _short_name(unique_id: str) -> str:
    """Convert dbt unique_id to short asset name.

    'model.data_reliability_lab.fct_daily_revenue' → 'fct_daily_revenue'
    'seed.data_reliability_lab.orders' → 'orders'
    'exposure.data_reliability_lab.ceo_revenue_dashboard' → 'ceo_revenue_dashboard'
    """
    parts = unique_id.split(".")
    return parts[-1] if len(parts) >= 3 else unique_id


_ASSET_TYPES = {"model", "seed", "exposure"}


def extract_dbt_dataset_graph(manifest_path: str | Path) -> dict[str, list[str]]:
    """Parse dbt manifest.json into a dataset lineage graph.

    Only includes models, seeds, and exposures — skips tests and macros.
    Node names are normalized to short names (last segment of unique_id).
    """
    path = Path(manifest_path)
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    graph: dict[str, list[str]] = {}
    child_map = manifest.get("child_map", {})

    for parent_id, children in child_map.items():
        parent_type = parent_id.split(".")[0]
        if parent_type not in _ASSET_TYPES:
            continue

        parent_name = _short_name(parent_id)
        asset_children = [
            _short_name(c)
            for c in children
            if c.split(".")[0] in _ASSET_TYPES
        ]

        if parent_name not in graph:
            graph[parent_name] = []
        graph[parent_name].extend(
            c for c in asset_children if c not in graph[parent_name]
        )

    # Include exposures from the exposures block (dbt >= 1.0)
    for exp_id, exp in manifest.get("exposures", {}).items():
        exp_name = _short_name(exp_id)
        for dep_id in exp.get("depends_on", {}).get("nodes", []):
            dep_type = dep_id.split(".")[0]
            if dep_type not in _ASSET_TYPES:
                continue
            dep_name = _short_name(dep_id)
            graph.setdefault(dep_name, [])
            if exp_name not in graph[dep_name]:
                graph[dep_name].append(exp_name)

    return graph
