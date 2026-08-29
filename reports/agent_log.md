# AI Agent Decision Log

## Decision 1 — Dùng Great Expectations thay custom validation
- Hypothesis: Cần validate contract rules (type, freshness, not-null) một cách có cấu trúc
- Prompt / request to agent: Phase 1 — chọn framework validation
- Agent proposal: Dùng Great Expectations (GX 1.21) với ExpectationSuite + Checkpoint; map từng contract rule sang GX expectation, gắn severity vào `meta`
- Evidence/test: `gx/validate_orders.py` chạy được ephemeral context, duplicate_pk bị BLOCKED đúng
- Accept / reject / revise: Accept
- Why: GX có sẵn expectation catalogue, Checkpoint/Actions pattern tách biệt validation logic khỏi action logic, severity trong `meta` cho phép phân loại critical/warning rõ ràng

## Decision 2 — Block on critical, quarantine file on warning
- Hypothesis: Không phải mọi violation đều nghiêm trọng như nhau — cần 2 mức xử lý khác nhau
- Prompt / request to agent: Phase 1 — khi contract fail thì làm gì
- Agent proposal: Critical → raise `DataBlockedError` dừng pipeline; Warning → copy file sang `data/quarantine/` + ghi metadata JSON (timestamp, violations)
- Evidence/test: Test với file có duplicate PK → BLOCKED; file có currency lạ → QUARANTINED + file xuất hiện trong `data/quarantine/`
- Accept / reject / revise: Accept
- Why: Tách biệt severity giúp pipeline không bị dừng vì warning nhỏ, đồng thời vẫn giữ file lỗi để audit sau

## Decision 3 — Expose SCD2 bug qua unit test trước, rồi mới fix model
- Hypothesis: `fct_daily_revenue` join `stg_customers` mà không filter `valid_to IS NULL` → nếu customer có 2 active SCD2 rows thì join fan-out, revenue bị nhân đôi
- Prompt / request to agent: Phase 2 — expose và fix SCD2 bug
- Agent proposal: Viết unit test inject 2 rows cùng customer_id (row 1 expired valid_to='2026-06-01', row 2 current valid_to=null), expect revenue=100 → test FAIL → fix model thêm `and valid_to is null` → test PASS
- Evidence/test: `duplicate_active_customer_inflates_revenue` unit test: trước fix FAIL (revenue=200), sau fix PASS (revenue=100)
- Accept / reject / revise: Accept
- Why: Viết test trước đảm bảo fix đúng behavior mong muốn, không chỉ làm test pass mà không verify logic

## Decision 4 — Auto mode: layered same-weekday → MAD → zscore
- Hypothesis: Z-score thuần sẽ sai khi history có outlier hoặc data có seasonality
- Prompt / request to agent: Phase 3 — nâng cấp `method="auto"` context-aware
- Agent proposal: 3 layer ưu tiên — (1) same-weekday MAD nếu context có ≥3 same-weekday points xử lý seasonality; (2) MAD trên full/segment history nếu ≥5 points xử lý outlier trong baseline; (3) zscore fallback khi data thưa
- Evidence/test: volume_drop (150/600 rows) detect được ở cả 3 layer; constant history (MAD=0) → score=inf thay vì bỏ sót
- Accept / reject / revise: Accept (thay vì chỉ MAD)
- Why: Chỉ MAD không xử lý được seasonality; layered approach cho phép chọn phương pháp phù hợp nhất với data có sẵn, fallback rõ ràng khi thiếu context
