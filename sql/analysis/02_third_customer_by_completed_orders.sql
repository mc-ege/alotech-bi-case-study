-- Exercise Query 2: third customer by number of completed orders.
WITH completed_orders AS (
  SELECT
    user_id,
    COUNT(*) AS completed_order_count
  FROM `alotech-bi-case-study.alotech_raw.orders`
  WHERE status = 'Complete'
  GROUP BY user_id
),
third_customer AS (
  SELECT
    user_id,
    completed_order_count
  FROM completed_orders
  QUALIFY ROW_NUMBER() OVER (
    ORDER BY completed_order_count DESC, user_id ASC
  ) = 3
)
SELECT
  t.user_id,
  u.first_name,
  u.last_name,
  u.email,
  t.completed_order_count
FROM third_customer AS t
JOIN `alotech-bi-case-study.alotech_raw.users` AS u
  ON t.user_id = u.id;
