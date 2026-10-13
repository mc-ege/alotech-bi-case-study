# AloTech BI engineering case study

This repository contains a Python and BigQuery workflow built on Google's public `thelook_ecommerce` dataset. It covers dataset creation, table ingestion, data checks, SQL analysis and a restricted users view.

Repository: https://github.com/mc-ege/alotech-bi-case-study  
Google Cloud project: `alotech-bi-case-study`  
BigQuery location: `US`

## Data layout

```text
bigquery-public-data.thelook_ecommerce
    orders | order_items | users | products
                    |
             Python copy jobs
                    |
             alotech_raw
                    |
          GoogleSQL checks and queries
                    |
         alotech_shared.v_users_contact

alotech_marts: reserved for reporting models
```

The pipeline copies the three required tables and `products`, which supplies names and categories for product analysis. It keeps the raw copies unchanged.

## Implementation

| Work | Files |
| --- | --- |
| Configuration and source schemas | `src/alotech_bi_case_study/config.py`, `contracts/source_schemas.py` |
| Dataset creation | `src/alotech_bi_case_study/ingestion/datasets.py`, `ingestion/provision.py` |
| Copy jobs and reconciliation | `src/alotech_bi_case_study/ingestion/copy_tables.py`, `ingestion/ingest.py` |
| JSON execution records | `src/alotech_bi_case_study/observability/run_log.py` |
| Data profiling and validation | `sql/profiling/`, `sql/validation/01_raw_data_quality.sql` |
| Analytical SQL | `sql/analysis/` |
| Contact view | `sql/views/01_users_contact_view.sql` |
| View access utility | `src/alotech_bi_case_study/sharing/grant_users_view_access.py` |
| Unit tests | `tests/unit/` |

The three analytical queries cover daily orders by status for 2023 and 2024, the third customer by completed-order count, and the most ordered product per month among completed orders. The final query ranks products by distinct orders and calculates each winning product's share of its month's completed-order item value.

## Recorded results

The initial ingestion copied four tables with matching source and destination row counts.

| Table | Rows |
| --- | ---: |
| `orders` | 125,416 |
| `order_items` | 181,946 |
| `users` | 100,000 |
| `products` | 29,120 |
| **Total** | **436,482** |

The BigQuery data-quality query returned 16 passing checks and one warning, with no critical failures. The warning concerns two products whose names are absent in the source. The daily order-status analysis for 2023 and 2024 returned 33,398 orders across 731 calendar dates.

Provisioning and ingestion receipts in `evidence/provisioning/` and `evidence/ingestion/` record Git revisions, UTC timestamps, results and BigQuery job IDs. These records document real cloud operations, not local test output.

## Reproduce the workflow

Use Python 3.13, `uv`, Google Cloud CLI and a Google Cloud project with BigQuery permissions. Configure Application Default Credentials and use a `US` dataset location to match the public source.

```bash
uv sync
export ALOTECH_PROJECT_ID="your-project-id"
export ALOTECH_LOCATION="US"
gcloud auth application-default login

# Commit local changes before applying cloud writes.
uv run python -m alotech_bi_case_study.ingestion.provision --apply
uv run python -m alotech_bi_case_study.ingestion.ingest --plan
uv run python -m alotech_bi_case_study.ingestion.ingest --apply

uv run ruff check src tests
uv run mypy src tests
uv run pytest tests/unit -q
```

Run the version-controlled SQL files in BigQuery Studio with the processing location set to `US`. The view SQL creates `alotech_shared.v_users_contact` with only `first_name`, `last_name` and `email`. The separate sharing utility handles view authorization and the named recipient's query permissions.

The project used BigQuery Sandbox with billing disabled. Google Cloud notebook setup required billing, so Python ran locally through `google-cloud-bigquery`, the table copies and SQL queries still executed in BigQuery. No cloud notebook runtime was needed.

For implementation details and the sequence of work, see [Technical overview](docs/TECHNICAL_OVERVIEW.md).
