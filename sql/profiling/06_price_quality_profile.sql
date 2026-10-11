-- Profiles price completeness, non-positive values, and observed ranges by order-item status.

SELECT
    status,
    COUNT(*) AS item_count,
    COUNTIF(sale_price IS NULL) AS null_prices,
    COUNTIF(sale_price = 0) AS zero_prices,
    COUNTIF(sale_price < 0) AS negative_prices,
    COUNTIF(IS_NAN(sale_price)) AS nan_prices,
    COUNTIF(IS_INF(sale_price)) AS infinite_prices,
    MIN(IF(IS_NAN(sale_price), NULL, sale_price)) AS min_price,
    MAX(IF(IS_NAN(sale_price), NULL, sale_price)) AS max_price
FROM `bigquery-public-data.thelook_ecommerce.order_items`
GROUP BY status
ORDER BY item_count DESC;
