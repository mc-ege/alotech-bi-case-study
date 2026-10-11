"""Failure-oriented offline tests for metadata-first, non-overwriting ingestion."""

from collections.abc import Callable
from types import SimpleNamespace
from typing import cast

import pytest
from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from alotech_bi_case_study.config import BigQueryConfig
from alotech_bi_case_study.contracts.source_schemas import SOURCE_FIELDS, source_schema
from alotech_bi_case_study.ingestion.copy_tables import (
    TablePlan,
    copy_missing,
    preflight,
)
from alotech_bi_case_study.observability.run_log import IngestionRun, Outcome

PROJECT = "alotech-bi-case-study"
CONFIG = BigQueryConfig(project_id=PROJECT, location="US")
SOURCE = "bigquery-public-data.thelook_ecommerce"
DEST = f"{PROJECT}.alotech_raw"
ROWS = {"orders": 125416, "order_items": 181946, "users": 100000, "products": 29120}


def _table(
    name: str, *, rows: int | None = None, size: int | None = 100
) -> bigquery.Table:
    return cast(
        bigquery.Table,
        SimpleNamespace(
            schema=source_schema(name),
            num_rows=ROWS[name] if rows is None else rows,
            num_bytes=size,
            table_type="TABLE",
            full_table_id=f"mock:{name}",
        ),
    )


class FakeJob:
    def __init__(
        self, job_id: str, finish: Callable[[], None], fail: bool = False
    ) -> None:
        self.job_id = job_id
        self._finish = finish
        self.fail = fail

    def result(self, *, timeout: int) -> None:
        assert timeout == 180
        if self.fail:
            raise RuntimeError("Job failed, raw error intentionally sensitive")
        self._finish()


class FakeClient:
    project = PROJECT

    def __init__(self) -> None:
        self.datasets = {SOURCE: "US", DEST: "US"}
        self.tables: dict[str, bigquery.Table] = {
            f"{SOURCE}.{name}": _table(name) for name in SOURCE_FIELDS
        }
        self.jobs: list[tuple[str, str, str]] = []
        self.fail_copy_at: str | None = None
        self.fail_job_at: str | None = None
        self.destination_row_override: int | None = None
        self.change_source_after_copy: str | None = None

    def get_dataset(self, identifier: str, *, timeout: int) -> bigquery.Dataset:
        assert timeout == 30
        try:
            location = self.datasets[identifier]
        except KeyError as exc:
            raise NotFound("Not found") from exc  # type: ignore[no-untyped-call]
        return cast(bigquery.Dataset, SimpleNamespace(location=location))

    def get_table(self, identifier: str, *, timeout: int) -> bigquery.Table:
        assert timeout == 30
        try:
            return self.tables[identifier]
        except KeyError as exc:
            raise NotFound("Not found") from exc  # type: ignore[no-untyped-call]

    def copy_table(
        self,
        source: str,
        destination: str,
        *,
        job_id: str,
        location: str,
        job_config: bigquery.CopyJobConfig,
        timeout: int,
    ) -> FakeJob:
        assert location == "US" and timeout == 30
        assert job_config.write_disposition == bigquery.WriteDisposition.WRITE_EMPTY
        name = source.rsplit(".", 1)[-1]
        if name == self.fail_copy_at:
            raise RuntimeError("API submission failed, secret bearer token")
        self.jobs.append((source, destination, job_id))

        def finish() -> None:
            if destination in self.tables:
                raise RuntimeError("WRITE_EMPTY prevented overwrite")
            self.tables[destination] = _table(
                name,
                rows=self.destination_row_override,
            )
            if name == self.change_source_after_copy:
                self.tables[source] = _table(name, rows=ROWS[name] + 1)

        return FakeJob(job_id, finish, fail=name == self.fail_job_at)


def _preflight(fake: FakeClient) -> tuple[TablePlan, ...]:
    return preflight(cast(bigquery.Client, fake), CONFIG)


def _copy(fake: FakeClient, run: IngestionRun) -> tuple[str, ...]:
    return copy_missing(cast(bigquery.Client, fake), CONFIG, _preflight(fake), run)


def test_preflight_all_four_sources_without_writes() -> None:
    fake = FakeClient()
    plans = _preflight(fake)
    assert [p.name for p in plans] == list(SOURCE_FIELDS)
    assert [p.rows for p in plans] == [ROWS[name] for name in SOURCE_FIELDS]
    assert not any(p.existing for p in plans)
    assert fake.jobs == []


@pytest.mark.parametrize("dataset", [SOURCE, DEST], ids=["source", "destination"])
def test_preflight_requires_both_datasets(dataset: str) -> None:
    fake = FakeClient()
    del fake.datasets[dataset]
    with pytest.raises(NotFound):
        _preflight(fake)


@pytest.mark.parametrize("dataset", [SOURCE, DEST], ids=["source", "destination"])
def test_preflight_rejects_wrong_location(dataset: str) -> None:
    fake = FakeClient()
    fake.datasets[dataset] = "EU"
    with pytest.raises(ValueError, match="incorrect location"):
        _preflight(fake)


def test_preflight_rejects_wrong_client_project() -> None:
    fake = FakeClient()
    fake.project = "another-project"
    with pytest.raises(ValueError, match="client project"):
        _preflight(fake)


def test_preflight_rejects_schema_drift() -> None:
    fake = FakeClient()
    source = fake.tables[f"{SOURCE}.users"]
    cast(SimpleNamespace, source).schema = source.schema[:-1]
    with pytest.raises(ValueError, match="missing column"):
        _preflight(fake)
    assert fake.jobs == []


@pytest.mark.parametrize("bad_size", [None, -1, False, "100", 1.5, 257 * 1024 * 1024])
def test_preflight_rejects_unknown_or_excessive_size(bad_size: object) -> None:
    fake = FakeClient()
    cast(SimpleNamespace, fake.tables[f"{SOURCE}.orders"]).num_bytes = bad_size
    with pytest.raises(ValueError, match="size|256 MiB"):
        _preflight(fake)


@pytest.mark.parametrize("bad_rows", [None, -1, True, "100", 1.5])
def test_preflight_rejects_unknown_rows(bad_rows: object) -> None:
    fake = FakeClient()
    cast(SimpleNamespace, fake.tables[f"{SOURCE}.orders"]).num_rows = bad_rows
    with pytest.raises(ValueError, match="row count"):
        _preflight(fake)


def test_existing_matching_table_is_preverified_and_skipped() -> None:
    fake = FakeClient()
    fake.tables[f"{DEST}.orders"] = _table("orders")
    plans = _preflight(fake)
    assert plans[0].existing
    run = IngestionRun()
    assert _copy(fake, run) == ("orders",)
    assert len(fake.jobs) == 3
    assert len(run.tables) == 3
    assert not any(record.table == "orders" for record in run.tables)


@pytest.mark.parametrize("problem", ["wrong_rows", "wrong_type", "wrong_schema"])
def test_existing_destination_drift_blocks_all_jobs(problem: str) -> None:
    fake = FakeClient()
    table = _table("orders", rows=1 if problem == "wrong_rows" else None)
    if problem == "wrong_type":
        cast(SimpleNamespace, table).table_type = "VIEW"
    elif problem == "wrong_schema":
        cast(SimpleNamespace, table).schema = source_schema("products")
    fake.tables[f"{DEST}.orders"] = table
    with pytest.raises(ValueError):
        _preflight(fake)
    assert fake.jobs == []


def test_copy_records_real_job_ids_and_validated_counts() -> None:
    fake = FakeClient()
    run = IngestionRun()
    assert _copy(fake, run) == ()
    run.finish()
    assert len(fake.jobs) == len(SOURCE_FIELDS)
    assert all(record.copy_status is Outcome.SUCCESS for record in run.tables)
    assert all(record.validation_status is Outcome.SUCCESS for record in run.tables)
    assert {record.source_rows for record in run.tables} == set(ROWS.values())
    assert {record.job_id for record in run.tables} == {j[2] for j in fake.jobs}
    assert all(str(run.run_id).replace("-", "") in j[2] for j in fake.jobs)
    assert run.to_dict()["status"] == "SUCCESS"


def test_second_preflight_skips_all_and_issues_no_jobs() -> None:
    fake = FakeClient()
    _copy(fake, IngestionRun())
    fake.jobs.clear()
    run = IngestionRun()
    assert _copy(fake, run) == tuple(SOURCE_FIELDS)
    assert fake.jobs == []
    assert run.tables == ()


def test_copy_submission_failure_preserves_attempted_job_id() -> None:
    fake = FakeClient()
    fake.fail_copy_at = "orders"
    run = IngestionRun()
    with pytest.raises(RuntimeError, match="submission"):
        _copy(fake, run)
    assert run.tables[0].copy_status is Outcome.FAILED
    # Identifier is an attempted job ID: API acceptance is not guaranteed.
    assert run.tables[0].job_id == f"alotech_{run.run_id.hex}_orders"
    assert len(run.tables) == 1


def test_job_failure_retains_job_id_for_investigation() -> None:
    fake = FakeClient()
    fake.fail_job_at = "orders"
    run = IngestionRun()
    with pytest.raises(RuntimeError, match="Job failed"):
        _copy(fake, run)
    assert run.tables[0].copy_status is Outcome.FAILED
    assert run.tables[0].job_id == fake.jobs[0][2]
    assert len(run.tables) == 1


@pytest.mark.parametrize("failure", ["destination_rows", "source_changed"])
def test_successful_copy_with_failed_validation_is_not_success(failure: str) -> None:
    fake = FakeClient()
    if failure == "destination_rows":
        fake.destination_row_override = 999
    else:
        fake.change_source_after_copy = "orders"
    run = IngestionRun()
    with pytest.raises(ValueError, match="validation|changed"):
        _copy(fake, run)
    record = run.tables[0]
    assert record.copy_status is Outcome.SUCCESS
    assert record.validation_status is Outcome.FAILED
    assert record.job_id == fake.jobs[0][2]


def test_copy_wait_timeout_preserves_attempted_job_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeClient()
    run = IngestionRun()

    def time_out(_job: FakeJob, *, timeout: int) -> None:
        assert timeout == 180
        raise TimeoutError("Local wait expired; cloud outcome unknown")

    monkeypatch.setattr(FakeJob, "result", time_out)
    with pytest.raises(TimeoutError, match="unknown"):
        _copy(fake, run)
    assert run.tables[0].copy_status is Outcome.FAILED
    assert run.tables[0].job_id == f"alotech_{run.run_id.hex}_orders"
    assert len(fake.jobs) == 1


def test_preflight_checks_total_size_across_tables() -> None:
    fake = FakeClient()
    for name in SOURCE_FIELDS:
        cast(SimpleNamespace, fake.tables[f"{SOURCE}.{name}"]).num_bytes = (
            80 * 1024 * 1024
        )
    with pytest.raises(ValueError, match="256 MiB"):
        _preflight(fake)
    assert fake.jobs == []


def test_partial_copy_failure_can_resume_without_overwrite() -> None:
    fake = FakeClient()
    fake.fail_job_at = "users"
    run = IngestionRun()
    with pytest.raises(RuntimeError, match="Job failed"):
        _copy(fake, run)
    assert [r.copy_status for r in run.tables] == [
        Outcome.SUCCESS,
        Outcome.SUCCESS,
        Outcome.FAILED,
    ]
    assert f"{DEST}.orders" in fake.tables
    assert f"{DEST}.order_items" in fake.tables
    assert f"{DEST}.users" not in fake.tables

    fake.fail_job_at = None
    fake.jobs.clear()
    resumed = IngestionRun()
    skipped = _copy(fake, resumed)
    assert skipped == ("orders", "order_items")
    assert [source.rsplit(".", 1)[-1] for source, _, _ in fake.jobs] == [
        "users",
        "products",
    ]
    assert all(r.validation_status is Outcome.SUCCESS for r in resumed.tables)
