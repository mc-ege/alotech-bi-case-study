-- Profiles order statuses, record counts, required-field nulls, and date ranges to establish data-quality expectations.

SELECT
    status,
    COUNT(*) AS order_count,
    COUNTIF(order_id IS NULL) AS null_order_ids,
    COUNTIF(user_id IS NULL) AS null_user_ids,
    COUNTIF(created_at IS NULL) AS null_created_dates,
    MIN(created_at) AS earliest_order,
    MAX(created_at) AS latest_order
FROM `bigquery-public-data.thelook_ecommerce.orders`
GROUP BY status
ORDER BY order_count DESC;
