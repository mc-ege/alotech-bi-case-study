-- Compares each order's declared item count with its actual order-item records.

WITH item_counts AS (
    SELECT
        order_id,
        COUNT(*) AS actual_item_count
    FROM `bigquery-public-data.thelook_ecommerce.order_items`
    GROUP BY order_id
)

SELECT
    COUNT(*) AS total_orders,
    COUNTIF(o.num_of_item IS NULL) AS null_declared_counts,
    COUNTIF(ic.order_id IS NULL) AS orders_without_items,
    COUNTIF(
        o.num_of_item IS DISTINCT FROM
        COALESCE(ic.actual_item_count, 0)
    ) AS mismatched_item_counts,
    COUNTIF(
        o.num_of_item IS NOT DISTINCT FROM
        COALESCE(ic.actual_item_count, 0)
    ) AS matching_item_counts
FROM `bigquery-public-data.thelook_ecommerce.orders` AS o
LEFT JOIN item_counts AS ic
    ON o.order_id = ic.order_id;
