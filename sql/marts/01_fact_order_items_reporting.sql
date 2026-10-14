-- Snapshot from validated alotech_raw tables, intentionally excludes contact details.
CREATE TABLE `alotech-bi-case-study.alotech_marts.fact_order_items_reporting`
OPTIONS (
  description = 'Order-item reporting snapshot for the AloTech two-page dashboard.'
)
AS
SELECT
  DATE(o.created_at, 'UTC') AS order_date,
  DATE_TRUNC(DATE(o.created_at, 'UTC'), MONTH) AS order_month,
  o.order_id,
  oi.id AS order_item_id,
  o.status AS order_status,
  IF(o.status = 'Complete', o.order_id, NULL) AS completed_order_id,
  IF(o.status = 'Cancelled', o.order_id, NULL) AS cancelled_order_id,
  u.country,
  u.gender,
  u.city,
  oi.product_id,
  COALESCE(NULLIF(TRIM(p.name), ''), FORMAT('Unknown Product (%d)', oi.product_id)) AS product_name,
  p.category AS product_category,
  ROUND(CAST(oi.sale_price AS NUMERIC), 2) AS item_amount,
  IF(
    o.status = 'Complete',
    ROUND(CAST(oi.sale_price AS NUMERIC), 2),
    NUMERIC '0'
  ) AS completed_item_amount
FROM `alotech-bi-case-study.alotech_raw.order_items` AS oi
JOIN `alotech-bi-case-study.alotech_raw.orders` AS o
  ON oi.order_id = o.order_id
JOIN `alotech-bi-case-study.alotech_raw.users` AS u
  ON o.user_id = u.id
JOIN `alotech-bi-case-study.alotech_raw.products` AS p
  ON oi.product_id = p.id;
