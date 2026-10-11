"""CLI tests: Git provenance, no-write default, safe failure receipts."""

import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest
from test_copy_tables import DEST, FakeClient, _table

from alotech_bi_case_study.contracts.source_schemas import SOURCE_FIELDS
from alotech_bi_case_study.ingestion.ingest import main


@pytest.fixture
def local_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ALOTECH_PROJECT_ID", "alotech-bi-case-study")
    monkeypatch.setenv("ALOTECH_LOCATION", "US")
    return tmp_path


def _receipt(root: Path) -> dict[str, Any]:
    [file] = (root / "evidence/ingestion").glob("*.json")
    return cast(dict[str, Any], json.loads(file.read_text(encoding="utf-8")))


def test_cli_blocks_dirty_checkout_before_cloud_access(local_config: Path) -> None:
    with (
        patch(
            "alotech_bi_case_study.ingestion.ingest._git",
            side_effect=["abc123", "?? untracked"],
        ),
        patch("alotech_bi_case_study.ingestion.ingest.bigquery.Client") as sdk_client,
    ):
        assert main(["--apply"]) == 1
        sdk_client.assert_not_called()
    record = _receipt(local_config)
    assert record["error_type"] == "GitStateError"
    assert record["partial_changes_possible"] is False


def test_default_mode_refuses_to_write_missing_tables(local_config: Path) -> None:
    fake = FakeClient()
    with (
        patch(
            "alotech_bi_case_study.ingestion.ingest._git", side_effect=["abc123", ""]
        ),
        patch(
            "alotech_bi_case_study.ingestion.ingest.bigquery.Client", return_value=fake
        ),
    ):
        assert main([]) == 1
    record = _receipt(local_config)
    assert record["error_type"] == "ValueError"
    assert fake.jobs == []
    assert record["operation"] == "verify_only"


def test_apply_creates_four_jobs_and_records_versioned_evidence(
    local_config: Path,
) -> None:
    fake = FakeClient()
    with (
        patch(
            "alotech_bi_case_study.ingestion.ingest._git", side_effect=["abc123", ""]
        ),
        patch(
            "alotech_bi_case_study.ingestion.ingest.bigquery.Client", return_value=fake
        ),
    ):
        assert main(["--apply"]) == 0
    record = _receipt(local_config)
    assert record["status"] == "SUCCESS"
    assert record["git_commit"] == "abc123"
    assert record["git_clean"] is True
    assert record["partial_changes_possible"] is False
    assert len(record["tables"]) == 4
    job_log = record["copy_run"]
    assert isinstance(job_log, dict)
    assert job_log["status"] == "SUCCESS"
    assert job_log["summary"]["tables_succeeded"] == 4
    assert {t["job_id"] for t in job_log["tables"]} == {j[2] for j in fake.jobs}
    assert len(record["skipped_verified"]) == 0


def test_verify_existing_never_starts_jobs_even_on_dirty_git(
    local_config: Path,
) -> None:
    fake = FakeClient()
    for name in SOURCE_FIELDS:
        fake.tables[f"{DEST}.{name}"] = _table(name)
    with (
        patch(
            "alotech_bi_case_study.ingestion.ingest._git",
            side_effect=["abc123", "?? evidence"],
        ),
        patch(
            "alotech_bi_case_study.ingestion.ingest.bigquery.Client", return_value=fake
        ),
    ):
        assert main([]) == 0
    record = _receipt(local_config)
    assert record["copy_run"] is None
    assert record["status"] == "SUCCESS"
    assert record["skipped_verified"] == list(SOURCE_FIELDS)
    assert fake.jobs == []


def test_repeated_apply_with_matching_tables_does_not_copy(local_config: Path) -> None:
    fake = FakeClient()
    for name in SOURCE_FIELDS:
        fake.tables[f"{DEST}.{name}"] = _table(name)
    with (
        patch(
            "alotech_bi_case_study.ingestion.ingest._git", side_effect=["abc123", ""]
        ),
        patch(
            "alotech_bi_case_study.ingestion.ingest.bigquery.Client", return_value=fake
        ),
    ):
        assert main(["--apply"]) == 0
    assert fake.jobs == []
    record = _receipt(local_config)
    assert record["copy_run"] is None
    assert record["skipped_verified"] == list(SOURCE_FIELDS)


def test_failed_second_job_records_partial_success_and_sanitizes_errors(
    local_config: Path,
) -> None:
    fake = FakeClient()
    fake.fail_job_at = "order_items"
    with (
        patch(
            "alotech_bi_case_study.ingestion.ingest._git", side_effect=["abc123", ""]
        ),
        patch(
            "alotech_bi_case_study.ingestion.ingest.bigquery.Client", return_value=fake
        ),
    ):
        assert main(["--apply"]) == 1
    record = _receipt(local_config)
    assert record["status"] == "FAILED"
    assert record["error_type"] == "RuntimeError"
    assert record["partial_changes_possible"] is True
    assert "raw error intentionally sensitive" not in json.dumps(record)
    job_log = record["copy_run"]
    assert isinstance(job_log, dict)
    assert job_log["status"] == "FAILED"
    assert job_log["summary"]["tables_succeeded"] == 1
    assert job_log["summary"]["tables_failed"] == 1
    assert len(fake.jobs) == 2


def test_missing_project_configuration_is_recorded(
    local_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ALOTECH_PROJECT_ID")
    with (
        patch(
            "alotech_bi_case_study.ingestion.ingest._git", side_effect=["abc123", ""]
        ),
        patch("alotech_bi_case_study.ingestion.ingest.bigquery.Client") as sdk_client,
    ):
        assert main(["--apply"]) == 1
        sdk_client.assert_not_called()
    assert _receipt(local_config)["error_type"] == "ValueError"


def test_plan_is_read_only_and_does_not_leave_untracked_receipts(
    local_config: Path,
) -> None:
    fake = FakeClient()
    with (
        patch(
            "alotech_bi_case_study.ingestion.ingest._git", side_effect=["abc123", ""]
        ),
        patch(
            "alotech_bi_case_study.ingestion.ingest.bigquery.Client", return_value=fake
        ),
    ):
        assert main(["--plan"]) == 0
    assert fake.jobs == []
    assert not (local_config / "evidence").exists()


def test_plan_rejects_invalid_location_without_writing(local_config: Path) -> None:
    fake = FakeClient()
    fake.datasets["bigquery-public-data.thelook_ecommerce"] = "EU"
    with (
        patch(
            "alotech_bi_case_study.ingestion.ingest._git", side_effect=["abc123", ""]
        ),
        patch(
            "alotech_bi_case_study.ingestion.ingest.bigquery.Client", return_value=fake
        ),
    ):
        assert main(["--plan"]) == 1
    assert fake.jobs == []
    assert not (local_config / "evidence").exists()


def test_plan_marks_only_existing_tables_as_skipped(
    local_config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeClient()
    fake.tables[f"{DEST}.orders"] = _table("orders")
    with (
        patch(
            "alotech_bi_case_study.ingestion.ingest._git", side_effect=["abc123", ""]
        ),
        patch(
            "alotech_bi_case_study.ingestion.ingest.bigquery.Client", return_value=fake
        ),
    ):
        assert main(["--plan"]) == 0
    output = capsys.readouterr().out
    assert "'table': 'orders'" in output
    assert "'already_present': True" in output
    assert "'already_present': False" in output
    assert not (local_config / "evidence").exists()


def test_copy_intent_receipt_exists_before_first_cloud_job(local_config: Path) -> None:
    fake = FakeClient()
    original = fake.copy_table
    seen = []

    def inspect_receipt(*args: Any, **kwargs: Any) -> Any:
        receipt = _receipt(local_config)
        seen.append(receipt["status"])
        assert receipt["partial_changes_possible"] is True
        assert receipt["copy_run"] is None
        return original(*args, **kwargs)

    with (
        patch(
            "alotech_bi_case_study.ingestion.ingest._git", side_effect=["abc123", ""]
        ),
        patch(
            "alotech_bi_case_study.ingestion.ingest.bigquery.Client", return_value=fake
        ),
        patch.object(fake, "copy_table", side_effect=inspect_receipt),
    ):
        assert main(["--apply"]) == 0
    assert seen == ["RUNNING"] * 4
    assert _receipt(local_config)["status"] == "SUCCESS"


def test_receipt_write_error_blocks_cloud_jobs(local_config: Path) -> None:
    from alotech_bi_case_study.ingestion.provision import _save_receipt

    fake = FakeClient()
    calls = 0

    def fail_first(record: dict[str, object], directory: Path) -> Path:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("Permission denied - do not include raw error")
        return _save_receipt(record, directory)

    with (
        patch(
            "alotech_bi_case_study.ingestion.ingest._git", side_effect=["abc123", ""]
        ),
        patch(
            "alotech_bi_case_study.ingestion.ingest.bigquery.Client", return_value=fake
        ),
        patch(
            "alotech_bi_case_study.ingestion.ingest._save_receipt",
            side_effect=fail_first,
        ),
    ):
        assert main(["--apply"]) == 1
    assert not fake.jobs
    receipt = _receipt(local_config)
    assert receipt["status"] == "FAILED"
    assert receipt["error_type"] == "OSError"
    assert receipt["partial_changes_possible"] is False
    assert "Permission denied" not in json.dumps(receipt)


def test_no_copy_results_cannot_report_success(local_config: Path) -> None:
    fake = FakeClient()
    with (
        patch(
            "alotech_bi_case_study.ingestion.ingest._git", side_effect=["abc123", ""]
        ),
        patch(
            "alotech_bi_case_study.ingestion.ingest.bigquery.Client", return_value=fake
        ),
        patch("alotech_bi_case_study.ingestion.ingest.copy_missing", return_value=()),
    ):
        assert main(["--apply"]) == 1
    record = _receipt(local_config)
    assert record["status"] == "FAILED"
    assert record["error_type"] == "RuntimeError"
    assert record["partial_changes_possible"] is True


def test_skip_results_must_match_preflight(local_config: Path) -> None:
    fake = FakeClient()
    for name in SOURCE_FIELDS:
        fake.tables[f"{DEST}.{name}"] = _table(name)
    with (
        patch(
            "alotech_bi_case_study.ingestion.ingest._git", side_effect=["abc123", ""]
        ),
        patch(
            "alotech_bi_case_study.ingestion.ingest.bigquery.Client", return_value=fake
        ),
        patch("alotech_bi_case_study.ingestion.ingest.copy_missing", return_value=()),
    ):
        assert main(["--apply"]) == 1
    assert _receipt(local_config)["error_type"] == "RuntimeError"


def test_failed_plan_reports_safe_exception_type(
    local_config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeClient()
    fake.datasets["bigquery-public-data.thelook_ecommerce"] = "EU"
    with (
        patch(
            "alotech_bi_case_study.ingestion.ingest._git", side_effect=["abc123", ""]
        ),
        patch(
            "alotech_bi_case_study.ingestion.ingest.bigquery.Client", return_value=fake
        ),
    ):
        assert main(["--plan"]) == 1
    output = capsys.readouterr().out
    assert "FAILED" in output and "ValueError" in output
    assert not (local_config / "evidence").exists()


def test_final_receipt_failure_preserves_initial_intent(
    local_config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from alotech_bi_case_study.ingestion.provision import _save_receipt

    fake = FakeClient()
    calls = 0

    def fail_final(record: dict[str, object], directory: Path) -> Path:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("Do not print raw filesystem error")
        return _save_receipt(record, directory)

    with (
        patch(
            "alotech_bi_case_study.ingestion.ingest._git", side_effect=["abc123", ""]
        ),
        patch(
            "alotech_bi_case_study.ingestion.ingest.bigquery.Client", return_value=fake
        ),
        patch(
            "alotech_bi_case_study.ingestion.ingest._save_receipt",
            side_effect=fail_final,
        ),
    ):
        assert main(["--apply"]) == 1
    assert len(fake.jobs) == 4
    assert _receipt(local_config)["status"] == "RUNNING"
    output = capsys.readouterr().err
    assert "receipt: FAILED | error=OSError" in output
    assert "Do not print raw" not in output
