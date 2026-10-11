-- Profiles foreign-key nulls and orphan records across orders, order_items, and users.

SELECT
    'orders.user_id -> users.id' AS relationship,
    COUNT(*) AS child_rows,
    COUNTIF(o.user_id IS NULL) AS null_foreign_keys,
    COUNTIF(o.user_id IS NOT NULL AND u.id IS NULL) AS orphan_rows
FROM `bigquery-public-data.thelook_ecommerce.orders` AS o
LEFT JOIN `bigquery-public-data.thelook_ecommerce.users` AS u
    ON o.user_id = u.id

UNION ALL

SELECT
    'order_items.order_id -> orders.order_id',
    COUNT(*),
    COUNTIF(oi.order_id IS NULL),
    COUNTIF(oi.order_id IS NOT NULL AND o.order_id IS NULL)
FROM `bigquery-public-data.thelook_ecommerce.order_items` AS oi
LEFT JOIN `bigquery-public-data.thelook_ecommerce.orders` AS o
    ON oi.order_id = o.order_id

UNION ALL

SELECT
    'order_items.user_id -> users.id',
    COUNT(*),
    COUNTIF(oi.user_id IS NULL),
    COUNTIF(oi.user_id IS NOT NULL AND u.id IS NULL)
FROM `bigquery-public-data.thelook_ecommerce.order_items` AS oi
LEFT JOIN `bigquery-public-data.thelook_ecommerce.users` AS u
    ON oi.user_id = u.id;
