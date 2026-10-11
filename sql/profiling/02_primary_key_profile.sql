-- Validates the uniqueness and non-nullness of candidate primary keys across orders, order_items, and users.

SELECT
    'orders' AS table_name,
    COUNT(*) AS row_count,
    COUNTIF(order_id IS NULL) AS null_keys,
    COUNT(order_id) - COUNT(DISTINCT order_id) AS duplicate_keys
FROM `bigquery-public-data.thelook_ecommerce.orders`

UNION ALL

SELECT
    'order_items',
    COUNT(*),
    COUNTIF(id IS NULL),
    COUNT(id) - COUNT(DISTINCT id)
FROM `bigquery-public-data.thelook_ecommerce.order_items`

UNION ALL

SELECT
    'users',
    COUNT(*),
    COUNTIF(id IS NULL),
    COUNT(id) - COUNT(DISTINCT id)
FROM `bigquery-public-data.thelook_ecommerce.users`;
