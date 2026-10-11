-- Daily order counts by source status, inclusive 2023-01-01 to 2024-12-31.
-- Calendar dates use UTC, matching BigQuery's default TIMESTAMP-to-DATE behavior.
SELECT
  DATE(created_at, 'UTC') AS order_date,
  status,
  COUNT(*) AS order_count
FROM `alotech-bi-case-study.alotech_raw.orders`
WHERE created_at >= TIMESTAMP '2023-01-01 00:00:00+00'
  AND created_at < TIMESTAMP '2025-01-01 00:00:00+00'
GROUP BY order_date, status
ORDER BY order_date, status;
