"""Metadata-first, non-overwriting BigQuery table copies for the case study."""

from dataclasses import dataclass

from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from alotech_bi_case_study.config import SOURCE_DATASET, SOURCE_PROJECT, BigQueryConfig
from alotech_bi_case_study.contracts.source_schemas import (
    SOURCE_FIELDS,
    validate_source_schema,
)
from alotech_bi_case_study.observability.run_log import (
    IngestionRun,
    Outcome,
    TableResult,
)

_REQUEST_TIMEOUT = 30
_JOB_TIMEOUT = 180
_MAX_SOURCE_BYTES = 256 * 1024 * 1024  # Conservative Sandbox safety limit.


@dataclass(frozen=True, slots=True)
class TablePlan:
    """A validated source and its corresponding destination at preflight time."""

    name: str
    source: str
    destination: str
    rows: int
    bytes: int
    existing: bool


def _nonnegative(value: object, label: str) -> int:
    """Reject absent, nonintegral or negative BigQuery metadata."""
    if type(value) is not int or value < 0:
        raise ValueError(f"Missing or invalid {label}")
    return value


def _rows(table: bigquery.Table) -> int:
    return _nonnegative(table.num_rows, f"row count: {table.full_table_id}")


def preflight(client: bigquery.Client, config: BigQueryConfig) -> tuple[TablePlan, ...]:
    """Validate both datasets, all sources and all existing targets; write nothing."""
    if client.project != config.project_id:
        raise ValueError("BigQuery client project differs from configuration")

    source_dataset = f"{SOURCE_PROJECT}.{SOURCE_DATASET}"
    destination_dataset = f"{config.project_id}.{config.raw_dataset}"
    for identifier in (source_dataset, destination_dataset):
        dataset = client.get_dataset(identifier, timeout=_REQUEST_TIMEOUT)
        if dataset.location != config.location:
            raise ValueError(
                f"Dataset {identifier} has incorrect location: {dataset.location}"
            )

    plans: list[TablePlan] = []
    total_bytes = 0
    for name in SOURCE_FIELDS:
        source_id = f"{source_dataset}.{name}"
        destination_id = f"{destination_dataset}.{name}"
        source = client.get_table(source_id, timeout=_REQUEST_TIMEOUT)
        validate_source_schema(name, list(source.schema))
        if source.table_type != "TABLE":
            raise ValueError(f"Source must be a physical table: {source_id}")
        rows = _rows(source)
        size = _nonnegative(source.num_bytes, f"table size: {source_id}")
        total_bytes += size
        if total_bytes > _MAX_SOURCE_BYTES:
            raise ValueError("Source exceeds the configured 256 MiB copy safety limit")

        try:
            target = client.get_table(destination_id, timeout=_REQUEST_TIMEOUT)
        except NotFound:
            existing = False
        else:
            existing = True
            validate_source_schema(name, list(target.schema))
            if target.table_type != "TABLE" or _rows(target) != rows:
                raise ValueError(
                    f"Existing destination does not match source: {destination_id}"
                )
        plans.append(TablePlan(name, source_id, destination_id, rows, size, existing))
    return tuple(plans)


def copy_missing(
    client: bigquery.Client,
    config: BigQueryConfig,
    plans: tuple[TablePlan, ...],
    run: IngestionRun,
) -> tuple[str, ...]:
    """Copy only missing tables and record actual jobs separately from skips.

    Jobs use WRITE_EMPTY: concurrent changes must fail, never overwrite data.
    Failed or timed-out attempts are logged, not automatically retried.
    An attempted job ID is not proof that BigQuery accepted the job.
    """
    skipped: list[str] = []
    for plan in plans:
        if plan.existing:
            skipped.append(plan.name)
            continue

        job_id = f"alotech_{run.run_id.hex}_{plan.name}"
        try:
            job = client.copy_table(
                plan.source,
                plan.destination,
                job_id=job_id,
                location=config.location,
                job_config=bigquery.CopyJobConfig(
                    write_disposition=bigquery.WriteDisposition.WRITE_EMPTY
                ),
                timeout=_REQUEST_TIMEOUT,
            )
            job.result(timeout=_JOB_TIMEOUT)
        except Exception:  # Record any unconfirmed copy outcome.
            run.add(
                TableResult(
                    plan.name,
                    Outcome.FAILED,
                    source_rows=plan.rows,
                    job_id=job_id,
                )
            )
            raise

        destination_rows: int | None = None
        try:
            destination = client.get_table(plan.destination, timeout=_REQUEST_TIMEOUT)
            destination_rows = _rows(destination)
            validate_source_schema(plan.name, list(destination.schema))
            if destination.table_type != "TABLE" or destination_rows != plan.rows:
                raise ValueError(
                    f"Copied destination failed validation: {plan.destination}"
                )
            latest = client.get_table(plan.source, timeout=_REQUEST_TIMEOUT)
            validate_source_schema(plan.name, list(latest.schema))
            if latest.table_type != "TABLE" or _rows(latest) != plan.rows:
                raise ValueError(f"Source changed during copy: {plan.source}")
        except Exception:  # Distinguish copy success from failed validation.
            run.add(
                TableResult(
                    plan.name,
                    Outcome.SUCCESS,
                    source_rows=plan.rows,
                    destination_rows=destination_rows,
                    job_id=job.job_id,
                    validation_status=Outcome.FAILED,
                )
            )
            raise
        run.add(
            TableResult(
                plan.name,
                Outcome.SUCCESS,
                source_rows=plan.rows,
                destination_rows=destination_rows,
                job_id=job.job_id,
                validation_status=Outcome.SUCCESS,
            )
        )
    return tuple(skipped)
