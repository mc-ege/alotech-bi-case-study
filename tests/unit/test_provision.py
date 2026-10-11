"""Offline and adversarial tests for reproducible dataset provisioning."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest
from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from alotech_bi_case_study.config import BigQueryConfig
from alotech_bi_case_study.ingestion.provision import _save_receipt, main, provision

PROJECT = "alotech-bi-case-study"
SOURCE = "bigquery-public-data.thelook_ecommerce"
TARGETS = tuple(
    f"{PROJECT}.{name}" for name in ("alotech_raw", "alotech_marts", "alotech_shared")
)
CONFIG = BigQueryConfig(project_id=PROJECT, location="US")


def _dataset(identifier: str, location: str = "US") -> bigquery.Dataset:
    dataset = bigquery.Dataset(identifier)
    dataset.location = location
    return dataset


class FakeClient:
    project = PROJECT

    def __init__(self) -> None:
        self.datasets: dict[str, bigquery.Dataset] = {SOURCE: _dataset(SOURCE)}
        self.creates: list[str] = []

    def get_dataset(self, identifier: str, *, timeout: int) -> bigquery.Dataset:
        assert timeout == 30
        try:
            return self.datasets[identifier]
        except KeyError as exc:
            raise NotFound("Missing") from exc  # type: ignore[no-untyped-call]

    def create_dataset(
        self, requested: bigquery.Dataset, *, exists_ok: bool, timeout: int
    ) -> bigquery.Dataset:
        assert exists_ok and timeout == 30
        identifier = f"{cast(str, requested.project)}.{cast(str, requested.dataset_id)}"
        self.creates.append(identifier)
        return self.datasets.setdefault(identifier, requested)


def _run(fake: FakeClient, *, apply: bool) -> list[dict[str, str | None]]:
    return provision(cast(bigquery.Client, fake), CONFIG, apply=apply)


def test_apply_creates_three_datasets_and_is_idempotent() -> None:
    client = FakeClient()
    assert [result["dataset_id"] for result in _run(client, apply=True)] == list(
        TARGETS
    )
    assert client.creates == list(TARGETS)
    _run(client, apply=True)
    assert client.creates == list(TARGETS)


def test_verify_only_does_not_create() -> None:
    client = FakeClient()
    with pytest.raises(NotFound):
        _run(client, apply=False)
    assert client.creates == []
    _run(client, apply=True)
    client.creates.clear()
    assert len(_run(client, apply=False)) == 3
    assert client.creates == []


@pytest.mark.parametrize("bad_location", ["EU", "europe-west4"])
def test_wrong_destination_location_rejected(bad_location: str) -> None:
    client = FakeClient()
    client.datasets[TARGETS[0]] = _dataset(TARGETS[0], bad_location)
    with pytest.raises(ValueError, match="expected 'US'"):
        _run(client, apply=True)
    assert client.creates == []


def test_source_location_checked_even_in_verify_mode() -> None:
    client = FakeClient()
    client.datasets[SOURCE].location = "EU"
    with pytest.raises(ValueError, match="Source dataset location"):
        _run(client, apply=False)
    assert client.creates == []


def test_receipt_is_parseable(tmp_path: Path) -> None:
    record: dict[str, object] = {"run_id": "abc", "status": "SUCCESS", "datasets": []}
    receipt = _save_receipt(record, tmp_path / "evidence")
    assert json.loads(receipt.read_text(encoding="utf-8")) == record
    assert list(receipt.parent.iterdir()) == [receipt]
    assert receipt.name == "abc.json"


def test_failed_atomic_replace_removes_temp_file(tmp_path: Path) -> None:
    with (
        patch(
            "alotech_bi_case_study.ingestion.provision.os.replace", side_effect=OSError
        ),
        pytest.raises(OSError),
    ):
        _save_receipt({"run_id": "failed"}, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_main_records_success_and_git_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALOTECH_PROJECT_ID", PROJECT)
    monkeypatch.setenv("ALOTECH_LOCATION", "US")
    monkeypatch.chdir(tmp_path)
    with (
        patch(
            "alotech_bi_case_study.ingestion.provision.bigquery.Client",
            return_value=FakeClient(),
        ),
        patch(
            "alotech_bi_case_study.ingestion.provision._git", side_effect=["abc123", ""]
        ),
    ):
        assert main(["--apply"]) == 0
    [path] = list((tmp_path / "evidence/provisioning").glob("*.json"))
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["status"] == "SUCCESS"
    assert record["git_commit"] == "abc123"
    assert record["git_clean"] is True
    assert record["operation"] == "apply"
    assert record["partial_changes_possible"] is False
    assert len(record["datasets"]) == 3
    assert datetime.fromisoformat(record["started_at_utc"]).tzinfo == UTC


@pytest.mark.parametrize(
    "revision,changes", [(None, None), ("abc123", " M src/file.py")]
)
def test_apply_refuses_uncommitted_or_unknown_source(
    revision: str | None,
    changes: str | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    with (
        patch(
            "alotech_bi_case_study.ingestion.provision._git",
            side_effect=[revision, changes],
        ),
        patch("alotech_bi_case_study.ingestion.provision.bigquery.Client") as client,
    ):
        assert main(["--apply"]) == 1
        client.assert_not_called()
    [path] = list((tmp_path / "evidence/provisioning").glob("*.json"))
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["error_type"] == "GitStateError"
    assert record["partial_changes_possible"] is False


def test_verify_works_even_in_dirty_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeClient()
    for target in TARGETS:
        client.datasets[target] = _dataset(target)
    monkeypatch.setenv("ALOTECH_PROJECT_ID", PROJECT)
    monkeypatch.setenv("ALOTECH_LOCATION", "US")
    monkeypatch.chdir(tmp_path)
    with (
        patch(
            "alotech_bi_case_study.ingestion.provision._git",
            side_effect=["abc", " M file"],
        ),
        patch(
            "alotech_bi_case_study.ingestion.provision.bigquery.Client",
            return_value=client,
        ),
    ):
        assert main([]) == 0
        assert client.creates == []


def test_main_failure_writes_sanitized_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALOTECH_PROJECT_ID", PROJECT)
    monkeypatch.setenv("ALOTECH_LOCATION", "US")
    monkeypatch.chdir(tmp_path)
    with (
        patch(
            "alotech_bi_case_study.ingestion.provision._git", side_effect=["abc123", ""]
        ),
        patch(
            "alotech_bi_case_study.ingestion.provision.bigquery.Client",
            side_effect=RuntimeError("SECRET_TOKEN"),
        ),
    ):
        assert main(["--apply"]) == 1
    [path] = list((tmp_path / "evidence/provisioning").glob("*.json"))
    payload = path.read_text(encoding="utf-8")
    assert "SECRET_TOKEN" not in payload
    assert json.loads(payload)["error_type"] == "RuntimeError"


def test_partial_creation_failure_is_flagged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class PartiallyFailingClient(FakeClient):
        def create_dataset(
            self, requested: bigquery.Dataset, *, exists_ok: bool, timeout: int
        ) -> bigquery.Dataset:
            if len(self.creates) == 1:
                raise RuntimeError("PRIVATE_ERROR")
            return super().create_dataset(
                requested, exists_ok=exists_ok, timeout=timeout
            )

    client = PartiallyFailingClient()
    monkeypatch.setenv("ALOTECH_PROJECT_ID", PROJECT)
    monkeypatch.setenv("ALOTECH_LOCATION", "US")
    monkeypatch.chdir(tmp_path)
    with (
        patch(
            "alotech_bi_case_study.ingestion.provision._git", side_effect=["abc123", ""]
        ),
        patch(
            "alotech_bi_case_study.ingestion.provision.bigquery.Client",
            return_value=client,
        ),
    ):
        assert main(["--apply"]) == 1
    [path] = list((tmp_path / "evidence/provisioning").glob("*.json"))
    payload = path.read_text(encoding="utf-8")
    assert "PRIVATE_ERROR" not in payload
    record = json.loads(payload)
    assert record["partial_changes_possible"] is True
    assert record["status"] == "FAILED"
    assert TARGETS[0] in client.datasets
    assert TARGETS[1] not in client.datasets
