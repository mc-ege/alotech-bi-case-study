"""Adversarial, offline tests for idempotent BigQuery dataset provisioning."""

from typing import cast
from unittest.mock import patch

import pytest
from google.api_core.exceptions import Forbidden, NotFound, ServiceUnavailable
from google.cloud import bigquery

from alotech_bi_case_study.config import BigQueryConfig
from alotech_bi_case_study.ingestion.datasets import ensure_datasets

PROJECT = "alotech-bi-case-study"
SOURCE = "bigquery-public-data.thelook_ecommerce"
TARGETS = tuple(
    f"{PROJECT}.{name}" for name in ("alotech_raw", "alotech_marts", "alotech_shared")
)


def _dataset(identifier: str, location: str | None = "US") -> bigquery.Dataset:
    dataset = bigquery.Dataset(identifier)
    dataset.location = location
    return dataset


class FakeClient:
    """Mimic only the documented Client methods used by ensure_datasets."""

    project = PROJECT

    def __init__(self) -> None:
        self.datasets = {SOURCE: _dataset(SOURCE)}
        self.creates: list[str] = []
        self.reads: list[str] = []
        self.race_locations: dict[str, str] = {}
        self.create_error_on: str | None = None
        self.read_error_on: str | None = None

    def get_dataset(self, identifier: str, *, timeout: int) -> bigquery.Dataset:
        assert timeout == 30
        self.reads.append(identifier)
        if identifier == self.read_error_on:
            raise Forbidden("Forbidden")  # type: ignore[no-untyped-call]
        try:
            return self.datasets[identifier]
        except KeyError as exc:
            raise NotFound("Not found") from exc  # type: ignore[no-untyped-call]

    def create_dataset(
        self, requested: bigquery.Dataset, *, exists_ok: bool, timeout: int
    ) -> bigquery.Dataset:
        assert timeout == 30
        assert exists_ok  # Required to safely reconcile simultaneous creation.
        identifier = f"{requested.project}.{requested.dataset_id}"
        self.creates.append(identifier)
        if identifier == self.create_error_on:
            raise Forbidden("Forbidden")  # type: ignore[no-untyped-call]
        if identifier in self.race_locations:
            self.datasets[identifier] = _dataset(
                identifier, self.race_locations[identifier]
            )
        if identifier in self.datasets:
            return self.datasets[identifier]
        self.datasets[identifier] = requested
        return requested


def _provision(fake: FakeClient, *, location: str = "US") -> tuple[str, ...]:
    config = BigQueryConfig(project_id=PROJECT, location=location)
    return ensure_datasets(cast(bigquery.Client, fake), config)


def test_creates_only_missing_datasets() -> None:
    client = FakeClient()
    client.datasets[TARGETS[0]] = _dataset(TARGETS[0])
    assert _provision(client) == TARGETS
    assert client.creates == list(TARGETS[1:])
    assert all(client.datasets[target].location == "US" for target in TARGETS)


def test_second_run_makes_no_create_calls() -> None:
    client = FakeClient()
    assert _provision(client) == TARGETS
    assert client.creates == list(TARGETS)
    client.creates.clear()
    assert _provision(client) == TARGETS
    assert client.creates == []


@pytest.mark.parametrize(
    "location", ["EU", "europe-west4", None], ids=["eu", "region", "unset"]
)
def test_bad_source_location_stops_before_writes(location: str | None) -> None:
    client = FakeClient()
    client.datasets[SOURCE] = _dataset(SOURCE, location)
    with pytest.raises(ValueError, match=r"thelook_ecommerce.*expected 'US'"):
        _provision(client)
    assert client.creates == []


@pytest.mark.parametrize("target", TARGETS, ids=["raw", "marts", "shared"])
def test_bad_existing_destination_stops_before_writes(target: str) -> None:
    client = FakeClient()
    client.datasets[target] = _dataset(target, "EU")
    with pytest.raises(ValueError, match=r"expected 'US'"):
        _provision(client)
    assert client.creates == []


def test_project_mismatch_stops_before_reads() -> None:
    client = FakeClient()
    client.project = "different-project"
    with pytest.raises(ValueError, match="client project"):
        _provision(client)
    assert client.reads == client.creates == []


def test_source_not_found_is_not_treated_as_missing_destination() -> None:
    client = FakeClient()
    del client.datasets[SOURCE]
    with pytest.raises(NotFound):
        _provision(client)
    assert client.creates == []


@pytest.mark.parametrize("location", ["US", "EU"], ids=["correct", "incorrect"])
def test_race_is_rechecked_after_create(location: str) -> None:
    client = FakeClient()
    client.race_locations[TARGETS[0]] = location
    if location == "EU":
        with pytest.raises(ValueError, match="expected 'US'"):
            _provision(client)
        assert TARGETS[1] not in client.datasets
    else:
        assert _provision(client) == TARGETS


@pytest.mark.parametrize("index", [0, 1, 2], ids=["first", "middle", "last"])
def test_create_permission_failure_propagates(index: int) -> None:
    client = FakeClient()
    client.create_error_on = TARGETS[index]
    with pytest.raises(Forbidden):
        _provision(client)
    assert client.creates == list(TARGETS[: index + 1])
    assert all(target not in client.datasets for target in TARGETS[index:])


def test_retry_after_partial_failure_only_creates_missing() -> None:
    client = FakeClient()
    client.create_error_on = TARGETS[1]
    with pytest.raises(Forbidden):
        _provision(client)
    client.create_error_on = None
    client.creates.clear()
    assert _provision(client) == TARGETS
    assert client.creates == list(TARGETS[1:])


@pytest.mark.parametrize(
    "identifier", [SOURCE, *TARGETS], ids=["source", "raw", "marts", "shared"]
)
def test_permission_error_on_read_propagates(identifier: str) -> None:
    client = FakeClient()
    client.read_error_on = identifier
    with pytest.raises(Forbidden):
        _provision(client)
    assert client.creates == []


def test_unexpected_api_errors_propagate() -> None:
    client = FakeClient()
    error = ServiceUnavailable("Temporarily unavailable")  # type: ignore[no-untyped-call]
    with (
        patch.object(client, "get_dataset", side_effect=error),
        pytest.raises(ServiceUnavailable),
    ):
        _provision(client)
    assert client.creates == []


@pytest.mark.parametrize(
    "failure",
    [NotFound, Forbidden],
    ids=["missing-after-create", "forbidden-after-create"],
)
def test_postcreate_metadata_failure_is_not_ignored(failure: type[Exception]) -> None:
    client = FakeClient()
    original_get = client.get_dataset

    def fail_on_refetch(identifier: str, *, timeout: int) -> bigquery.Dataset:
        if identifier == TARGETS[0] and identifier in client.datasets:
            raise failure("Post-create verification failed")
        return original_get(identifier, timeout=timeout)

    with (
        patch.object(client, "get_dataset", side_effect=fail_on_refetch),
        pytest.raises(failure),
    ):
        _provision(client)
    assert client.creates == [TARGETS[0]]
