"""Validated, environment-driven BigQuery identifiers; no network access.

The public source is fixed for the assignment; destinations are configurable.
Validation checks identifier *syntax*, not resource existence or source location.
"""

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Self

# Official naming constraints for ordinary Google Cloud project IDs.
_PROJECT_ID = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]\Z")
# Dataset IDs permit letters, numbers, underscores. Leading '_' is excluded
# intentionally because such datasets are hidden in BigQuery's Explorer.
_DATASET_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_]{0,1023}\Z")
# Basic syntactic guard, not an authoritative list of supported GCP regions.
_LOCATION = re.compile(r"(?:US|EU|[a-z]+(?:-[a-z0-9]+)*[0-9])\Z")

SOURCE_PROJECT = "bigquery-public-data"
SOURCE_DATASET = "thelook_ecommerce"


def _require_match(value: object, pattern: re.Pattern[str], field: str) -> None:
    """Reject missing, malformed, or non-string configuration values."""
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ValueError(f"Invalid {field}: expected a valid identifier, got {value!r}")


@dataclass(frozen=True, slots=True, kw_only=True)
class BigQueryConfig:
    """Immutable identifiers used by the ingestion and reporting pipeline.

    `location` must be checked against the actual source dataset before any
    destination dataset is created; this module only validates its syntax.
    """

    project_id: str
    location: str
    raw_dataset: str = "alotech_raw"
    mart_dataset: str = "alotech_marts"
    shared_dataset: str = "alotech_shared"

    def __post_init__(self) -> None:
        """Fail fast on unsafe project IDs, dataset IDs, and locations."""
        _require_match(self.project_id, _PROJECT_ID, "project_id")
        _require_match(self.location, _LOCATION, "location")
        names = (self.raw_dataset, self.mart_dataset, self.shared_dataset)
        for name in names:
            _require_match(name, _DATASET_ID, "dataset_id")
        if len({name.casefold() for name in names}) != len(names):
            raise ValueError("Destination dataset IDs must be distinct")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Self:
        """Read settings from a supplied mapping or the process environment.

        Accepting a mapping makes tests independent of the developer's machine.
        No credentials, access tokens, or service-account files are read here.
        """
        values = os.environ if environ is None else environ
        return cls(
            project_id=values.get("ALOTECH_PROJECT_ID", ""),
            location=values.get("ALOTECH_LOCATION", ""),
            raw_dataset=values.get("ALOTECH_RAW_DATASET", "alotech_raw"),
            mart_dataset=values.get("ALOTECH_MART_DATASET", "alotech_marts"),
            shared_dataset=values.get("ALOTECH_SHARED_DATASET", "alotech_shared"),
        )
