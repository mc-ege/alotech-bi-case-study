"""CLI for reproducible BigQuery dataset provisioning and verification."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from google.cloud import bigquery

from alotech_bi_case_study.config import SOURCE_DATASET, SOURCE_PROJECT, BigQueryConfig
from alotech_bi_case_study.ingestion.datasets import ensure_datasets

_TIMEOUT = 30


class GitStateError(RuntimeError):
    """A cloud write cannot be linked to a clean, committed source revision."""


def _git(*args: str) -> str | None:
    """Return a Git command's stdout, or None if Git is unavailable."""
    try:
        result = subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def provision(
    client: bigquery.Client, config: BigQueryConfig, *, apply: bool
) -> list[dict[str, str | None]]:
    """Provision or read-only verify all configured datasets and their locations."""
    if apply:
        targets = ensure_datasets(client, config)
    else:
        if client.project != config.project_id:
            raise ValueError("BigQuery client project differs from configuration")
        source = client.get_dataset(
            f"{SOURCE_PROJECT}.{SOURCE_DATASET}", timeout=_TIMEOUT
        )
        if source.location != config.location:
            raise ValueError("Source dataset location differs from configuration")
        targets = tuple(
            f"{config.project_id}.{name}"
            for name in (config.raw_dataset, config.mart_dataset, config.shared_dataset)
        )

    results: list[dict[str, str | None]] = []
    for target in targets:
        dataset = client.get_dataset(target, timeout=_TIMEOUT)
        if dataset.location != config.location:
            raise ValueError(f"Dataset {target} has incorrect location")
        results.append(
            {
                "dataset_id": target,
                "location": dataset.location,
                "created_at": dataset.created.isoformat() if dataset.created else None,
            }
        )
    return results


def _save_receipt(record: dict[str, object], directory: Path) -> Path:
    """Write one JSON receipt atomically, cleaning temporary files on failure."""
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{record['run_id']}.json"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=directory, delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump(record, handle, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination


def main(argv: list[str] | None = None) -> int:
    """Require a clean, committed Git revision for writes; record each run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Create missing datasets")
    parser.add_argument(
        "--evidence-dir", type=Path, default=Path("evidence/provisioning")
    )
    args = parser.parse_args(argv)

    revision = _git("rev-parse", "--verify", "HEAD")
    changes = _git("status", "--porcelain", "--untracked-files=all")
    record: dict[str, object] = {
        "run_id": str(uuid4()),
        "started_at_utc": datetime.now(UTC).isoformat(),
        "git_commit": revision,
        "git_clean": changes == "" if changes is not None else None,
        "operation": "apply" if args.apply else "verify_only",
        "status": "FAILED",
        "datasets": [],
        "error_type": None,
        "partial_changes_possible": False,
    }
    try:
        if args.apply and (not revision or changes != ""):
            raise GitStateError("Commit all changes before applying provisioning")
        config = BigQueryConfig.from_env()
        record.update(project_id=config.project_id, location=config.location)
        client = bigquery.Client(project=config.project_id, location=config.location)
        record["partial_changes_possible"] = args.apply
        record["datasets"] = provision(client, config, apply=args.apply)
        record["status"] = "SUCCESS"
        record["partial_changes_possible"] = False
    except Exception as exc:  # noqa: BLE001 - Capture unexpected CLI failures.
        record["error_type"] = type(exc).__name__  # Never save raw API error details.
    finally:
        record["finished_at_utc"] = datetime.now(UTC).isoformat()
        receipt = _save_receipt(record, args.evidence_dir)
        print(
            f"{record['operation']}: {record['status']} "
            f"| error={record['error_type']} | receipt={receipt}"
        )
    return 0 if record["status"] == "SUCCESS" else 1


if __name__ == "__main__":
    sys.exit(main())
