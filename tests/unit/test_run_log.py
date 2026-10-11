"""Adversarial tests for ingestion status, JSON audit files, and failure safety."""

import json
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest

from alotech_bi_case_study.observability.run_log import (
    IngestionRun,
    Outcome,
    TableResult,
    save_run,
)


def result(
    table: str = "orders",
    copy: Outcome = Outcome.SUCCESS,
    validation: Outcome | None = Outcome.SUCCESS,
) -> TableResult:
    """Build a valid outcome to make each test mutation specific."""
    return TableResult(table, copy, 3, 3, "job-1", validation)


def test_run_uuid_v4_is_unique() -> None:
    first, second = IngestionRun(), IngestionRun()
    assert first.run_id != second.run_id
    assert UUID(str(first.run_id)).version == 4


def test_running_to_success_snapshot_and_atomic_replacement(tmp_path: Path) -> None:
    run = IngestionRun()
    path = save_run(run, tmp_path / "ingestion")
    assert json.loads(path.read_text())["status"] == "RUNNING"
    run.add(result())
    run.finish()
    assert save_run(run, tmp_path / "ingestion") == path
    data = json.loads(path.read_text())
    assert data["status"] == "SUCCESS"
    assert data["tables"][0]["validation_status"] == "SUCCESS"
    assert data["tables"][0]["copy_status"] == "SUCCESS"
    assert isinstance(data["duration_seconds"], float)
    assert data["summary"] == {
        "tables_processed": 1,
        "tables_succeeded": 1,
        "tables_failed": 0,
        "tables_pending_validation": 0,
    }
    assert data["started_at"].endswith("+00:00")
    assert data["finished_at"].endswith("+00:00")
    assert [p.name for p in path.parent.glob("*.json")] == [path.name]


@pytest.mark.parametrize(
    ("copy", "validation", "expected"),
    [
        (Outcome.SUCCESS, Outcome.SUCCESS, "SUCCESS"),
        (Outcome.SUCCESS, Outcome.FAILED, "FAILED"),
        (Outcome.FAILED, None, "FAILED"),
        (Outcome.SUCCESS, None, "FAILED"),
    ],
    ids=["both-passed", "validation-failed", "copy-failed", "unvalidated"],
)
def test_finished_run_requires_successful_copy_and_validation(
    copy: Outcome, validation: Outcome | None, expected: str
) -> None:
    run = IngestionRun()
    run.add(result(copy=copy, validation=validation))
    run.finish()
    assert run.to_dict()["status"] == expected


@pytest.mark.parametrize(
    "count",
    [-1, 1.2, True, "42", [], {}],
    ids=["negative", "float", "bool", "string", "list", "dict"],
)
@pytest.mark.parametrize("name", ["source_rows", "destination_rows"])
def test_bad_counts_rejected(name: str, count: object) -> None:
    with pytest.raises(ValueError, match=name):
        TableResult("orders", Outcome.SUCCESS, **{name: count})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "table",
    ["", "not a table", "orders.id", "../escape", "éclair", None, 5],
    ids=["empty", "space", "dot", "traversal", "unicode", "none", "integer"],
)
def test_bad_table_names_rejected(table: object) -> None:
    with pytest.raises(ValueError, match="table"):
        TableResult(cast(str, table), Outcome.SUCCESS)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("copy_status", "SUCCESS"),
        ("copy_status", None),
        ("copy_status", 1),
        ("validation_status", "SUCCESS"),
        ("validation_status", 1),
    ],
    ids=[
        "copy-string",
        "copy-none",
        "copy-integer",
        "quality-string",
        "quality-integer",
    ],
)
def test_invalid_outcomes_rejected(name: str, value: object) -> None:
    values: dict[str, object] = {
        "copy_status": Outcome.SUCCESS,
        "validation_status": Outcome.SUCCESS,
    }
    values[name] = value
    with pytest.raises(TypeError, match=name):
        TableResult("orders", **values)  # type: ignore[arg-type]


def test_contradictory_validation_status_rejected() -> None:
    with pytest.raises(ValueError, match="validation cannot succeed"):
        result(copy=Outcome.FAILED)


@pytest.mark.parametrize("job_id", ["", "   ", 123], ids=["empty", "blank", "integer"])
def test_invalid_job_ids_rejected(job_id: object) -> None:
    with pytest.raises(ValueError, match="job_id"):
        TableResult("orders", Outcome.SUCCESS, job_id=cast(str, job_id))


@pytest.mark.parametrize(
    "started_at",
    [datetime(2026, 10, 11), None, "2026-10-11"],
    ids=["naive", "none", "string"],
)
def test_invalid_timestamps_rejected(started_at: object) -> None:
    with pytest.raises(ValueError, match="started_at"):
        IngestionRun(started_at=cast(datetime, started_at))


def test_failure_without_table_is_recorded_but_empty_success_rejected() -> None:
    run = IngestionRun()
    with pytest.raises(ValueError, match="no tables"):
        run.finish()
    run.finish(error=RuntimeError("private error content"))
    assert run.to_dict()["status"] == "FAILED"
    assert run.to_dict()["error_type"] == "RuntimeError"


def test_duplicate_late_writes_and_multiple_finishes_rejected() -> None:
    run = IngestionRun()
    run.add(result())
    with pytest.raises(ValueError, match="duplicate"):
        run.add(result())
    run.finish()
    with pytest.raises(RuntimeError, match="finished"):
        run.add(result("users"))
    with pytest.raises(RuntimeError, match="already finished"):
        run.finish()
    with pytest.raises(AttributeError):
        run.tables.append(result("users"))  # type: ignore[attr-defined]


def test_run_summarizes_mixed_statuses() -> None:
    run = IngestionRun()
    for item in [
        result("orders"),
        result("users", validation=Outcome.FAILED),
        result("products", validation=None),
    ]:
        run.add(item)
    run.finish()
    assert run.to_dict()["summary"] == {
        "tables_processed": 3,
        "tables_succeeded": 1,
        "tables_failed": 1,
        "tables_pending_validation": 1,
    }
    assert run.to_dict()["status"] == "FAILED"


def test_exception_message_is_never_logged(tmp_path: Path) -> None:
    run = IngestionRun()
    run.finish(error=RuntimeError("SECRET TOKEN"))
    contents = save_run(run, tmp_path).read_text()
    assert "SECRET TOKEN" not in contents
    assert '"error_type": "RuntimeError"' in contents


def test_table_record_is_immutable() -> None:
    item = result()
    with pytest.raises(FrozenInstanceError):
        item.table = "users"  # type: ignore[misc]


def test_invalid_run_id_does_not_write(tmp_path: Path) -> None:
    run = IngestionRun()
    run.run_id = cast(UUID, "../../escape")
    with pytest.raises(TypeError, match="run_id"):
        save_run(run, tmp_path)
    assert not list(tmp_path.iterdir())


def test_invalid_table_record_rejected() -> None:
    with pytest.raises(TypeError, match="TableResult"):
        IngestionRun().add(cast(TableResult, None))


@pytest.mark.parametrize("prior_snapshot", [False, True], ids=["new", "existing"])
@pytest.mark.parametrize("failure_point", ["fsync", "replace"])
def test_write_failure_cleans_tmp_and_preserves_old_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prior_snapshot: bool,
    failure_point: str,
) -> None:
    run = IngestionRun()
    path = tmp_path / f"{run.run_id}.json"
    if prior_snapshot:
        save_run(run, tmp_path)
    before = path.read_bytes() if path.exists() else None
    run.add(result())

    def fail_write(*_args: object) -> None:
        raise OSError("injected failure")

    monkeypatch.setattr(
        f"alotech_bi_case_study.observability.run_log.os.{failure_point}", fail_write
    )
    with pytest.raises(OSError, match="injected failure"):
        save_run(run, tmp_path)
    assert (path.read_bytes() if path.exists() else None) == before
    assert not list(tmp_path.glob("*.tmp"))


def test_input_timezone_is_normalized_to_utc() -> None:
    istanbul = timezone(timedelta(hours=3))
    started_at = datetime(2026, 10, 11, 12, 0, tzinfo=istanbul)
    run = IngestionRun(started_at=started_at)
    assert run.to_dict()["started_at"] == "2026-10-11T09:00:00+00:00"


def test_invalid_error_argument_rejected() -> None:
    with pytest.raises(TypeError, match="error"):
        IngestionRun().finish(error=cast(BaseException, "not an exception"))
