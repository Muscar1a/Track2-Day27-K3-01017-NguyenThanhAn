-- Total revenue in the mart must equal total completed-order amount from staging.
-- Returns 1 row (test fails) when a fan-out join inflates revenue.
select 1
where (
    select coalesce(sum(daily_revenue), 0) from {{ ref('fct_daily_revenue') }}
) <> (
    select coalesce(sum(amount_usd), 0) from {{ ref('stg_orders') }}
    where status = 'completed'
)
