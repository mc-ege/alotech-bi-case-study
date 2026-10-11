-- Checks that every order item belongs to the same user as its parent order.

SELECT
    COUNT(*) AS order_item_rows,
    COUNTIF(
        oi.user_id IS DISTINCT FROM o.user_id
    ) AS mismatched_user_ids
FROM `bigquery-public-data.thelook_ecommerce.order_items` AS oi
JOIN `bigquery-public-data.thelook_ecommerce.orders` AS o
    ON oi.order_id = o.order_id;
