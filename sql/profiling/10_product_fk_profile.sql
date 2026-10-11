-- Checks whether each order item has a non-null product ID referencing an existing product.

SELECT
    COUNT(*) AS order_item_rows,
    COUNTIF(oi.product_id IS NULL) AS null_product_ids,
    COUNTIF(oi.product_id IS NOT NULL AND p.id IS NULL) AS orphan_product_ids,
    COUNTIF(p.id IS NOT NULL) AS matched_product_ids
FROM `bigquery-public-data.thelook_ecommerce.order_items` AS oi
LEFT JOIN `bigquery-public-data.thelook_ecommerce.products` AS p
    ON oi.product_id = p.id;
