-- Identifies products without names and measures their associated order-item and completed-item activity.

SELECT
    p.id AS product_id,
    p.name,
    p.category,
    COUNT(oi.id) AS related_order_items,
    COUNT(DISTINCT oi.order_id) AS related_orders,
    COUNTIF(oi.status = 'Complete') AS completed_order_items
FROM `bigquery-public-data.thelook_ecommerce.products` AS p
LEFT JOIN `bigquery-public-data.thelook_ecommerce.order_items` AS oi
    ON p.id = oi.product_id
WHERE p.name IS NULL
   OR TRIM(p.name) = ''
GROUP BY p.id, p.name, p.category
ORDER BY p.id;
