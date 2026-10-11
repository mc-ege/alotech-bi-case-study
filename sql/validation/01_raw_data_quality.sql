-- Read-only validation of the ingested snapshot (run 72cd1924-981e-410b-b21c-6bacb0a4ce0a).
-- Exact row-count baselines refer to that run, not the evolving public source.
-- ERROR findings fail validation; WARNING findings are reported without failing it.

WITH
  orders_metrics AS (
    SELECT
      COUNT(*) AS row_count,
      COUNT(*) - COUNT(DISTINCT order_id) AS invalid_keys,
      COUNTIF(status IS NULL OR status NOT IN (
        'Complete', 'Shipped', 'Processing', 'Cancelled', 'Returned'
      )) AS unexpected_statuses
    FROM `alotech-bi-case-study.alotech_raw.orders`
  ),
  items_metrics AS (
    SELECT
      COUNT(*) AS row_count,
      COUNT(*) - COUNT(DISTINCT id) AS invalid_keys,
      COUNTIF(
        sale_price IS NULL OR IS_NAN(sale_price) OR IS_INF(sale_price)
        OR sale_price <= 0
      ) AS invalid_prices
    FROM `alotech-bi-case-study.alotech_raw.order_items`
  ),
  users_metrics AS (
    SELECT COUNT(*) AS row_count, COUNT(*) - COUNT(DISTINCT id) AS invalid_keys
    FROM `alotech-bi-case-study.alotech_raw.users`
  ),
  products_metrics AS (
    SELECT
      COUNT(*) AS row_count,
      COUNT(*) - COUNT(DISTINCT id) AS invalid_keys,
      COUNTIF(name IS NULL OR TRIM(name) = '') AS unnamed_products
    FROM `alotech-bi-case-study.alotech_raw.products`
  ),
  item_relationships AS (
    SELECT
      COUNTIF(i.order_id IS NULL OR o.order_id IS NULL) AS missing_orders,
      COUNTIF(i.user_id IS NULL OR u.id IS NULL) AS missing_users,
      COUNTIF(i.product_id IS NULL OR p.id IS NULL) AS missing_products,
      COUNTIF(o.order_id IS NOT NULL AND i.user_id IS DISTINCT FROM o.user_id)
        AS mismatched_order_users
    FROM `alotech-bi-case-study.alotech_raw.order_items` AS i
    LEFT JOIN `alotech-bi-case-study.alotech_raw.orders` AS o
      ON i.order_id = o.order_id
    LEFT JOIN `alotech-bi-case-study.alotech_raw.users` AS u
      ON i.user_id = u.id
    LEFT JOIN `alotech-bi-case-study.alotech_raw.products` AS p
      ON i.product_id = p.id
  ),
  order_relationships AS (
    SELECT COUNTIF(o.user_id IS NULL OR u.id IS NULL) AS missing_users
    FROM `alotech-bi-case-study.alotech_raw.orders` AS o
    LEFT JOIN `alotech-bi-case-study.alotech_raw.users` AS u
      ON o.user_id = u.id
  ),
  item_counts AS (
    SELECT COUNTIF(o.num_of_item IS NULL OR o.num_of_item != IFNULL(i.n, 0))
      AS incorrect_item_counts
    FROM `alotech-bi-case-study.alotech_raw.orders` AS o
    LEFT JOIN (
      SELECT order_id, COUNT(*) AS n
      FROM `alotech-bi-case-study.alotech_raw.order_items`
      GROUP BY order_id
    ) AS i ON o.order_id = i.order_id
  ),
  checks AS (
    SELECT check_name, severity, issues
    FROM orders_metrics
    CROSS JOIN UNNEST(ARRAY<STRUCT<check_name STRING, severity STRING, issues INT64>>[
      ('orders.row_count', 'ERROR', ABS(row_count - 125416)),
      ('orders.primary_key', 'ERROR', invalid_keys),
      ('orders.known_status', 'WARNING', unexpected_statuses)
    ])
    UNION ALL
    SELECT check_name, severity, issues
    FROM items_metrics
    CROSS JOIN UNNEST(ARRAY<STRUCT<check_name STRING, severity STRING, issues INT64>>[
      ('order_items.row_count', 'ERROR', ABS(row_count - 181946)),
      ('order_items.primary_key', 'ERROR', invalid_keys),
      ('order_items.valid_sale_price', 'ERROR', invalid_prices)
    ])
    UNION ALL
    SELECT check_name, severity, issues
    FROM users_metrics
    CROSS JOIN UNNEST(ARRAY<STRUCT<check_name STRING, severity STRING, issues INT64>>[
      ('users.row_count', 'ERROR', ABS(row_count - 100000)),
      ('users.primary_key', 'ERROR', invalid_keys)
    ])
    UNION ALL
    SELECT check_name, severity, issues
    FROM products_metrics
    CROSS JOIN UNNEST(ARRAY<STRUCT<check_name STRING, severity STRING, issues INT64>>[
      ('products.row_count', 'ERROR', ABS(row_count - 29120)),
      ('products.primary_key', 'ERROR', invalid_keys),
      ('products.name_present', 'WARNING', unnamed_products)
    ])
    UNION ALL
    SELECT check_name, severity, issues
    FROM item_relationships
    CROSS JOIN UNNEST(ARRAY<STRUCT<check_name STRING, severity STRING, issues INT64>>[
      ('order_items.order_fk', 'ERROR', missing_orders),
      ('order_items.user_fk', 'ERROR', missing_users),
      ('order_items.product_fk', 'ERROR', missing_products),
      ('order_items.user_matches_order', 'ERROR', mismatched_order_users)
    ])
    UNION ALL
    SELECT 'orders.user_fk', 'ERROR', missing_users FROM order_relationships
    UNION ALL
    SELECT 'orders.item_count_matches', 'ERROR', incorrect_item_counts FROM item_counts
  )
SELECT
  check_name,
  severity,
  issues,
  CASE
    WHEN issues = 0 THEN 'PASS'
    WHEN severity = 'WARNING' THEN 'WARN'
    ELSE 'FAIL'
  END AS result
FROM checks
ORDER BY
  CASE WHEN severity = 'ERROR' AND issues > 0 THEN 0
       WHEN issues > 0 THEN 1 ELSE 2 END,
  check_name;
