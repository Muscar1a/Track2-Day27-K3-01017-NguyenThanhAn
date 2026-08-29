# Incident Report

## Severity
P2

## Summary
Partial ingestion fault reduced incoming orders from ~600 rows (expected weekday/weekend baseline)
to 150 rows (25% of normal volume). Revenue reporting and the CEO dashboard were at risk of
under-counting. Anomaly detector caught the drop; contract checks passed (no schema violation).

## Detection
- Signal: `row-count anomaly = True` (auto:same_weekday MAD, score=7.86)
- First observed time: 2026-08-29 ~05:04 UTC (Phase 3 baseline run)
- Detector: `detect_anomaly` auto mode — same-weekday MAD baseline (weekend median=258, incoming=150)

## Root Cause
`inject_fault.py volume_drop` kept only 25% of rows (150/600) via a truncation of the ingestion
file before it reached the pipeline. No schema errors, no duplicate keys — the data was
structurally valid but volumetrically incomplete. Z-score alone missed the anomaly (score=2.22 <
threshold=3.0) because the high weekday variance in history diluted the signal; same-weekday MAD
correctly isolated the weekend baseline and detected the drop.

## Evidence
1. `make baseline` output: `orders rows: 150`, `row-count anomaly: True (auto:mad, score=7.86)`
2. `detect_anomaly(150, weekend_history=[258, 274, ...], method="auto")` → score=6.36, is_anomaly=True
3. `get_downstream_assets(graph, "stg_orders")` → `["fct_daily_revenue", "ceo_revenue_dashboard"]`

## Blast Radius

```text
stg_orders (150 rows instead of ~600)
  -> fct_daily_revenue   [daily_revenue under-counted by ~75%]
      -> ceo_revenue_dashboard  [P&L report shows false low revenue]

Column-level:
  raw_orders.amount -> stg_orders.amount_usd -> fct_daily_revenue.daily_revenue -> ceo_revenue_dashboard.revenue
```

## Mitigation
- Anomaly alert triggered immediately on ingestion run.
- Pipeline can be blocked or flagged; downstream models re-run once full dataset arrives.
- No data corruption — quarantine not needed (contract passed, only volume was low).

## Recovery
Re-ingest full orders dataset → re-run `dbt build` → verify `fct_daily_revenue` row count and
`daily_revenue` sum matches expected range.

## Verification
- [x] Contract healthy (no schema/type/freshness violations)
- [x] dbt tests healthy (PASS=20 after re-ingest)
- [x] anomaly returned to expected range (score < 3.0 on full dataset)
- [x] SLO healthy / budget understood (burn_rate < 1.0 when no bad checks)
- [x] downstream output verified (daily_revenue matches sum of completed orders)

## Prevention / Action Items
| Action | Owner | Deadline | Why |
|---|---|---|---|
| Add row-count lower-bound contract rule | commerce-data | 2026-09-05 | Catch volume drop at contract layer before anomaly detector |
| Alert on same-weekday MAD score > 4.0 | platform-eng | 2026-09-05 | Current threshold=3.0 fires at minor fluctuations; tune to reduce noise |
| Add ingestion completeness check (source record count vs loaded count) | data-eng | 2026-09-12 | Detect truncation at source before data enters pipeline |
