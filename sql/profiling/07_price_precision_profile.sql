-- Measures price deviations from two decimal places and compares FLOAT64 versus NUMERIC aggregation.

WITH price_profile AS (
    SELECT
        status,
        sale_price,
        ABS(
            sale_price - ROUND(sale_price, 2)
        ) AS deviation_from_two_decimals,
        ROUND(
            CAST(sale_price AS NUMERIC), 2
        ) AS normalized_price
    FROM `bigquery-public-data.thelook_ecommerce.order_items`
)

SELECT
    status,
    COUNT(*) AS item_count,
    MAX(deviation_from_two_decimals) AS max_deviation,
    COUNTIF(
        deviation_from_two_decimals > 0.001
    ) AS prices_above_tolerance,
    SUM(sale_price) AS total_float,
    SUM(normalized_price) AS total_numeric
FROM price_profile
GROUP BY status
ORDER BY item_count DESC;
