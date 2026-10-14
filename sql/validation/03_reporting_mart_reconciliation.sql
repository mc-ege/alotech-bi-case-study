-- A single row of validation metrics. All discrepancies should equal zero.
WITH mart AS (
  SELECT
    COUNT(*) AS mart_rows,
    COUNT(DISTINCT order_item_id) AS unique_items,
    COUNT(DISTINCT order_id) AS distinct_orders,
    COUNT(DISTINCT completed_order_id) AS completed_orders,
    COUNT(DISTINCT cancelled_order_id) AS cancelled_orders,
    COUNTIF(order_date IS NULL OR order_month IS NULL) AS missing_dates,
    COUNTIF(country IS NULL OR gender IS NULL OR city IS NULL) AS missing_customer_dimensions,
    COUNTIF(product_category IS NULL) AS missing_category,
    COUNTIF(item_amount IS NULL OR item_amount <= 0) AS invalid_amounts,
    COUNTIF(order_date < DATE '2019-01-01') AS anomalous_dates
  FROM `alotech-bi-case-study.alotech_marts.fact_order_items_reporting`
), raw AS (
  SELECT
    (SELECT COUNT(*) FROM `alotech-bi-case-study.alotech_raw.order_items`) AS source_rows,
    (SELECT COUNT(*) FROM `alotech-bi-case-study.alotech_raw.orders`) AS source_orders,
    (SELECT COUNTIF(status = 'Complete') FROM `alotech-bi-case-study.alotech_raw.orders`) AS source_completed,
    (SELECT COUNTIF(status = 'Cancelled') FROM `alotech-bi-case-study.alotech_raw.orders`) AS source_cancelled
)
SELECT
  mart_rows,
  source_rows,
  mart_rows - source_rows AS row_difference,
  mart_rows - unique_items AS duplicate_item_ids,
  distinct_orders - source_orders AS order_difference,
  completed_orders - source_completed AS completed_order_difference,
  cancelled_orders - source_cancelled AS cancelled_order_difference,
  missing_dates,
  missing_customer_dimensions,
  missing_category,
  invalid_amounts,
  anomalous_dates
FROM mart CROSS JOIN raw;
