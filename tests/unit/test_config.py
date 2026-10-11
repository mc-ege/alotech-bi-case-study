"""Adversarial configuration tests: all operate locally, without GCP calls."""

from dataclasses import FrozenInstanceError, replace
from typing import cast

import pytest

from alotech_bi_case_study.config import (
    SOURCE_DATASET,
    SOURCE_PROJECT,
    BigQueryConfig,
)

_VALID = {"ALOTECH_PROJECT_ID": "alotech-bi-case-study", "ALOTECH_LOCATION": "US"}


def test_load_default_configuration() -> None:
    """Required settings load and all optional datasets have stable names."""
    config = BigQueryConfig.from_env(_VALID)
    assert (config.project_id, config.location) == ("alotech-bi-case-study", "US")
    assert (config.raw_dataset, config.mart_dataset, config.shared_dataset) == (
        "alotech_raw",
        "alotech_marts",
        "alotech_shared",
    )
    assert (SOURCE_PROJECT, SOURCE_DATASET) == (
        "bigquery-public-data",
        "thelook_ecommerce",
    )


@pytest.mark.parametrize("missing", ["ALOTECH_PROJECT_ID", "ALOTECH_LOCATION"])
def test_missing_required_setting_is_rejected(missing: str) -> None:
    """A missing required setting must never silently select another project."""
    with pytest.raises(ValueError):
        BigQueryConfig.from_env(
            {key: value for key, value in _VALID.items() if key != missing}
        )


@pytest.mark.parametrize(
    "invalid",
    [
        "",
        "ab",
        "A-project",
        "1project",
        "abcde-",
        "bad_project",
        "abc.def",
        " withspace",
        pytest.param("a" * 31, id="too-long"),
        None,
        123,
    ],
)
def test_invalid_project_ids_are_rejected(invalid: object) -> None:
    """Malformed IDs must fail before any BigQuery operation can be invoked."""
    with pytest.raises(ValueError, match="project_id"):
        replace(BigQueryConfig.from_env(_VALID), project_id=cast(str, invalid))


@pytest.mark.parametrize(
    "invalid",
    [
        "",
        "bad-name",
        "has space",
        ".",
        "_hidden",
        pytest.param("a" * 1025, id="too-long"),
        None,
        13,
    ],
)
@pytest.mark.parametrize("attribute", ["raw_dataset", "mart_dataset", "shared_dataset"])
def test_invalid_dataset_ids_are_rejected(attribute: str, invalid: object) -> None:
    """Reject invalid identifiers in every configurable destination dataset."""
    with pytest.raises(ValueError, match="dataset_id"):
        replace(BigQueryConfig.from_env(_VALID), **{attribute: cast(str, invalid)})


@pytest.mark.parametrize(
    "location", ["", "us", "us ", "moon!", "EU;", "us-central", None, 1]
)
def test_invalid_locations_are_rejected(location: object) -> None:
    """Location spelling mistakes and non-strings must fail immediately."""
    with pytest.raises(ValueError, match="location"):
        replace(BigQueryConfig.from_env(_VALID), location=cast(str, location))


@pytest.mark.parametrize("location", ["US", "EU", "us-central1", "europe-west4"])
def test_valid_location_shapes_are_accepted(location: str) -> None:
    """Accept documented location formats; actual source location is checked later."""
    result = replace(BigQueryConfig.from_env(_VALID), location=location)
    assert result.location == location


def test_duplicate_dataset_names_are_rejected() -> None:
    """Prevent writing multiple logical layers to the same destination dataset."""
    with pytest.raises(ValueError, match="distinct"):
        replace(BigQueryConfig.from_env(_VALID), shared_dataset="ALOTECH_RAW")


def test_environment_overrides_are_honored() -> None:
    """The assessor can choose their own project and dataset identifiers."""
    values = _VALID | {
        "ALOTECH_PROJECT_ID": "reviewer-project-123",
        "ALOTECH_RAW_DATASET": "review_raw",
        "ALOTECH_MART_DATASET": "review_mart",
        "ALOTECH_SHARED_DATASET": "review_shared",
    }
    config = BigQueryConfig.from_env(values)
    actual = (
        config.project_id,
        config.raw_dataset,
        config.mart_dataset,
        config.shared_dataset,
    )
    assert actual == (
        "reviewer-project-123",
        "review_raw",
        "review_mart",
        "review_shared",
    )


def test_mapping_does_not_fall_back_to_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken explicit configuration cannot silently use the developer's project."""
    monkeypatch.setenv("ALOTECH_PROJECT_ID", "another-project-123")
    monkeypatch.setenv("ALOTECH_LOCATION", "US")
    with pytest.raises(ValueError, match="project_id"):
        BigQueryConfig.from_env({"ALOTECH_LOCATION": "US"})


def test_environment_is_used_when_no_mapping_is_supplied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default construction reads process variables only on explicit request."""
    monkeypatch.setenv("ALOTECH_PROJECT_ID", "alotech-bi-case-study")
    monkeypatch.setenv("ALOTECH_LOCATION", "US")
    assert BigQueryConfig.from_env().project_id == "alotech-bi-case-study"


def test_configuration_is_immutable() -> None:
    """Prevent later code from silently retargeting a validated pipeline."""
    config = BigQueryConfig.from_env(_VALID)
    with pytest.raises(FrozenInstanceError):
        config.project_id = "changed-project"  # type: ignore[misc]
