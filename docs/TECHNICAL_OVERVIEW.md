# AloTech BI engineering: technical overview

I built the BigQuery workflow using Python for resource creation and ingestion, and GoogleSQL for data validation and analysis. The source was Google's public `bigquery-public-data.thelook_ecommerce` dataset. I kept the code, SQL and evidence of cloud executions in [GitHub](https://github.com/mc-ege/alotech-bi-case-study).

## 1. Set up the project

I created the `alotech-bi-case-study` Google Cloud project and initialized a Python 3.13 package in Git. I used `uv` to manage dependencies, `pytest` for tests, Ruff for formatting and linting, and mypy for type checks. The application uses Google's `google-cloud-bigquery` client. I configured Application Default Credentials locally instead of placing credentials in the repository.

Billing was the main environment constraint. I wanted to run the case study without linking a billing account. BigQuery Sandbox allowed dataset creation, server-side table copies and SQL queries within its free limits. BigQuery Studio notebooks required billing during setup, so I kept Python execution local and used BigQuery Studio for SQL. Python still submitted jobs to BigQuery; it did not download and re-upload the source tables.

## 2. Inspect the source before copying it

I inspected the `orders`, `order_items` and `users` schemas in BigQuery Studio and added `products` because the product query needed names and categories. Profiling SQL checked row counts, primary keys, relationships, order-item ownership, item counts and sale prices. I saved the SQL in `sql/profiling/` rather than relying on query history.

I encoded the observed physical schemas as Python contracts. Before any copy, the ingestion process compares live BigQuery metadata with those contracts and checks that the source and destination use the `US` location. This prevents a changed source schema or wrong dataset location from silently passing into ingestion.

## 3. Create the destination datasets

I split the project into `alotech_raw` for source copies, `alotech_shared` for controlled views and `alotech_marts` for reporting models. The Python provisioning command creates missing datasets, checks their locations and can be rerun without duplicating resources.

I committed the provisioning code before running it. The first cloud execution created all three datasets, and a second read-only run verified their original creation timestamps. JSON receipts record the Git commit and the observed results.

## 4. Copy and verify the tables

The ingestion command first builds a read-only plan. Its live run then submits four BigQuery table-copy jobs, one per source table. It avoids overwriting populated destination tables and records job IDs so individual operations can be investigated.

All four jobs completed successfully. The destination held **125,416 orders**, **181,946 order items**, **100,000 users** and **29,120 products**, or **436,482 rows** in total. Post-copy checks matched each destination's schema and row count to the source snapshot. These checks do not claim a full row-by-row comparison. Since the copy jobs are independent, the receipt also records whether a failed run might have left partial changes.

## 5. Run data-quality checks

I wrote a single GoogleSQL validation query with 17 named checks and executed it in BigQuery Studio. It tests primary-key uniqueness, expected row counts, foreign-key references, order-item ownership, item-count agreement, sale-price validity and order statuses.

The result was **16 PASS, 1 WARN and no critical failures**. Two products lacked names. I kept the source values unchanged and treated the missing names as a warning. The checks and their results establish data integrity at the tested level without disguising a source-data issue.

## 6. Write the analytical SQL

I saved three SQL queries under `sql/analysis/` and ran them in BigQuery Studio. The first groups orders by day and status for 2023 and 2024; its exported result covers **731 dates and 33,398 orders**. The second counts completed orders per customer and uses `ROW_NUMBER()` with a stable user-ID tie-breaker to select the third customer. The third finds the most ordered product in each month among completed orders and calculates its share of monthly completed-order item value.

The product query counts distinct orders and joins product details after aggregation. Source prices are floating-point values, so it rounds to cents for reporting rather than changing stored raw values.

## 7. Create the users view

Finally, I created `alotech-bi-case-study.alotech_shared.v_users_contact`. The view reads `alotech_raw.users` and selects only `first_name`, `last_name` and `email`. Its SQL lives in `sql/views/`. A separate Python utility in `sharing/` contains the authorized-view and recipient-access operations, so permissions are handled apart from the view definition.

The result is a reproducible Python ETL process with BigQuery execution evidence, version-controlled data checks and SQL queries, and a limited users projection. The code and saved SQL are the source of truth; the BigQuery project contains the deployed data and view.
