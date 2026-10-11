"""Safely provision the three configured BigQuery datasets in the source location."""

from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from alotech_bi_case_study.config import (
    SOURCE_DATASET,
    SOURCE_PROJECT,
    BigQueryConfig,
)

_REQUEST_TIMEOUT = 30  # Seconds per API request, not a global execution deadline.


def _require_location(dataset: bigquery.Dataset, expected: str) -> None:
    """Reject datasets whose actual location differs from the configured one."""
    if dataset.location != expected:
        raise ValueError(
            f"Dataset {dataset.project}.{dataset.dataset_id} is in "
            f"{dataset.location!r}; expected {expected!r}"
        )


def ensure_datasets(client: bigquery.Client, config: BigQueryConfig) -> tuple[str, ...]:
    """Create missing datasets only, after validating all existing locations.

    A rerun is non-destructive. This is not a transaction: earlier creates may
    remain if a later request fails, and a subsequent run can safely resume.
    """
    if client.project != config.project_id:
        raise ValueError("BigQuery client project differs from configuration")

    source_id = f"{SOURCE_PROJECT}.{SOURCE_DATASET}"
    _require_location(
        client.get_dataset(source_id, timeout=_REQUEST_TIMEOUT), config.location
    )

    targets = tuple(
        f"{config.project_id}.{dataset_id}"
        for dataset_id in (
            config.raw_dataset,
            config.mart_dataset,
            config.shared_dataset,
        )
    )
    missing: list[str] = []

    # Check every existing destination before creating any missing dataset.
    for target in targets:
        try:
            existing = client.get_dataset(target, timeout=_REQUEST_TIMEOUT)
        except NotFound:
            missing.append(target)
        else:
            _require_location(existing, config.location)

    for target in missing:
        requested = bigquery.Dataset(target)
        requested.location = config.location
        client.create_dataset(requested, exists_ok=True, timeout=_REQUEST_TIMEOUT)
        # exists_ok handles concurrent creation but not an incorrect location.
        _require_location(
            client.get_dataset(target, timeout=_REQUEST_TIMEOUT), config.location
        )

    return targets
