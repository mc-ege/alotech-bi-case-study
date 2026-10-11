-- Exercise Query 3: Most-ordered product per month, restricted to completed orders.
-- Month is based on orders.created_at (UTC); order counts are distinct orders.
-- Amounts sum item sale prices, rounded to cents as a reporting convention.
WITH product_month AS (
  SELECT
    DATE_TRUNC(DATE(o.created_at, 'UTC'), MONTH) AS order_month,
    oi.product_id,
    COUNT(DISTINCT oi.order_id) AS number_of_orders,
    SUM(ROUND(CAST(oi.sale_price AS NUMERIC), 2)) AS total_order_amount
  FROM `alotech-bi-case-study.alotech_raw.order_items` AS oi
  JOIN `alotech-bi-case-study.alotech_raw.orders` AS o
    ON oi.order_id = o.order_id
  WHERE o.status = 'Complete'
  GROUP BY order_month, oi.product_id
),
monthly_winner AS (
  SELECT
    *,
    SUM(total_order_amount) OVER (PARTITION BY order_month) AS monthly_completed_revenue
  FROM product_month
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY order_month
    ORDER BY number_of_orders DESC, product_id ASC
  ) = 1
)
SELECT
  w.order_month,
  w.product_id,
  p.name AS product_name,
  w.number_of_orders,
  w.total_order_amount,
  ROUND(
    100 * SAFE_DIVIDE(w.total_order_amount, w.monthly_completed_revenue), 2
  ) AS revenue_contribution_pct
FROM monthly_winner AS w
JOIN `alotech-bi-case-study.alotech_raw.products` AS p
  ON w.product_id = p.id
ORDER BY w.order_month;
