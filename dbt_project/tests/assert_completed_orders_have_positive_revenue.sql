-- Days with completed orders must have positive revenue.
select *
from {{ ref('fct_daily_revenue') }}
where completed_order_rows > 0
  and daily_revenue <= 0
