"""Atomic local JSON snapshots of ingestion runs (no secrets or error messages)."""

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import UUID, uuid4


class Outcome(StrEnum):
    """Copy and validation outcomes."""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class TableResult:
    """A table copy and its independent data-quality result.

    A missing validation result means validation has not completed, not success.
    """

    table: str
    copy_status: Outcome
    source_rows: int | None = None
    destination_rows: int | None = None
    job_id: str | None = None
    validation_status: Outcome | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.table, str)
            or not self.table.isascii()
            or not self.table.isidentifier()
        ):
            raise ValueError("table must be an ASCII identifier")
        if not isinstance(self.copy_status, Outcome):
            raise TypeError("copy_status must be an Outcome")
        if self.validation_status is not None and not isinstance(
            self.validation_status, Outcome
        ):
            raise TypeError("validation_status must be an Outcome or None")
        if (
            self.copy_status is Outcome.FAILED
            and self.validation_status is Outcome.SUCCESS
        ):
            raise ValueError("validation cannot succeed when copy failed")
        for name in ("source_rows", "destination_rows"):
            count = getattr(self, name)
            if count is not None and (
                isinstance(count, bool) or not isinstance(count, int) or count < 0
            ):
                raise ValueError(f"{name} must be a nonnegative integer or None")
        if self.job_id is not None and (
            not isinstance(self.job_id, str) or not self.job_id.strip()
        ):
            raise ValueError("job_id must be a nonempty string or None")


@dataclass(slots=True)
class IngestionRun:
    """One execution; record each table once and finalize exactly once."""

    run_id: UUID = field(default_factory=uuid4)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = field(default=None, init=False)
    error_type: str | None = field(default=None, init=False)
    _tables: list[TableResult] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, UUID):
            raise TypeError("run_id must be a UUID")
        if (
            not isinstance(self.started_at, datetime)
            or self.started_at.utcoffset() is None
        ):
            raise ValueError("started_at must be a timezone-aware datetime")

    @property
    def tables(self) -> tuple[TableResult, ...]:
        """Expose immutable table results, preserving their recorded order."""
        return tuple(self._tables)

    def add(self, result: TableResult) -> None:
        """Record a table's outcome without allowing duplicates or late writes."""
        if not isinstance(result, TableResult):
            raise TypeError("result must be a TableResult")
        if self.finished_at is not None:
            raise RuntimeError("cannot modify a finished run")
        if any(item.table == result.table for item in self._tables):
            raise ValueError(f"duplicate table result: {result.table}")
        self._tables.append(result)

    def finish(self, *, error: BaseException | None = None) -> None:
        """Finalize, recording exception type only (never its message)."""
        if self.finished_at is not None:
            raise RuntimeError("run is already finished")
        if error is not None and not isinstance(error, BaseException):
            raise TypeError("error must be an exception or None")
        if error is None and not self._tables:
            raise ValueError("cannot successfully finish a run with no tables")
        self.error_type = type(error).__name__ if error is not None else None
        self.finished_at = datetime.now(UTC)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible snapshot with separate copy/quality counts."""
        success = sum(
            t.copy_status is Outcome.SUCCESS and t.validation_status is Outcome.SUCCESS
            for t in self._tables
        )
        failed = sum(
            t.copy_status is Outcome.FAILED or t.validation_status is Outcome.FAILED
            for t in self._tables
        )
        pending = len(self._tables) - success - failed
        if self.finished_at is None:
            status = "RUNNING"
        else:
            status = (
                "FAILED"
                if self.error_type or failed or pending or not self._tables
                else "SUCCESS"
            )
        return {
            "run_id": str(self.run_id),
            "started_at": self.started_at.astimezone(UTC).isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration_seconds": (
                round((self.finished_at - self.started_at).total_seconds(), 3)
                if self.finished_at
                else None
            ),
            "status": status,
            "tables": [asdict(t) for t in self._tables],
            "summary": {
                "tables_processed": len(self._tables),
                "tables_succeeded": success,
                "tables_failed": failed,
                "tables_pending_validation": pending,
            },
            "error_type": self.error_type,
        }


def save_run(run: IngestionRun, directory: Path) -> Path:
    """Replace a snapshot atomically; preserve the old file on write failure."""
    if not isinstance(run.run_id, UUID):
        raise TypeError("run_id must be a UUID")
    payload = json.dumps(run.to_dict(), indent=2, allow_nan=False) + "\n"
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{run.run_id}.json"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=directory,
            prefix=".ingestion-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination
