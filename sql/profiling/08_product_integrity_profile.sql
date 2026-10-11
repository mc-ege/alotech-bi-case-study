-- Profiles product-key integrity and completeness of required reporting attributes.

SELECT
    COUNT(*) AS product_rows,
    COUNTIF(id IS NULL) AS null_product_ids,
    COUNT(id) - COUNT(DISTINCT id) AS duplicate_product_ids,
    COUNTIF(name IS NULL OR TRIM(name) = '') AS missing_product_names,
    COUNTIF(category IS NULL OR TRIM(category) = '') AS missing_categories
FROM `bigquery-public-data.thelook_ecommerce.products`;
