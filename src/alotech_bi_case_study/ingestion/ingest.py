"""Reproducible BigQuery table ingestion: read-only verification by default."""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from google.cloud import bigquery

from alotech_bi_case_study.config import BigQueryConfig
from alotech_bi_case_study.ingestion.copy_tables import copy_missing, preflight
from alotech_bi_case_study.ingestion.provision import GitStateError, _git, _save_receipt
from alotech_bi_case_study.observability.run_log import IngestionRun, Outcome


def main(argv: list[str] | None = None) -> int:
    """Preflight, optionally copy missing tables, and record cloud writes."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--apply", action="store_true", help="Copy only missing source tables"
    )
    mode.add_argument(
        "--plan", action="store_true", help="Check copy candidates without writing"
    )
    parser.add_argument("--evidence-dir", type=Path, default=Path("evidence/ingestion"))
    args = parser.parse_args(argv)

    run = IngestionRun()
    revision = _git("rev-parse", "--verify", "HEAD")
    changes = _git("status", "--porcelain", "--untracked-files=all")
    record: dict[str, object] = {
        "run_id": str(run.run_id),
        "git_commit": revision,
        "git_clean": changes == "" if changes is not None else None,
        "started_at_utc": run.started_at.isoformat(),
        "operation": "apply" if args.apply else "plan" if args.plan else "verify_only",
        "status": "FAILED",
        "tables": [],
        "skipped_verified": [],
        "copy_run": None,
        "error_type": None,
        "partial_changes_possible": False,
    }
    failure: Exception | None = None
    try:
        if args.apply and (not revision or changes != ""):
            raise GitStateError("Commit all changes before copying tables")
        config = BigQueryConfig.from_env()
        record.update(project_id=config.project_id, location=config.location)
        client = bigquery.Client(project=config.project_id, location=config.location)
        plans = preflight(client, config)
        record["tables"] = [
            {
                "table": plan.name,
                "source": plan.source,
                "destination": plan.destination,
                "source_rows": plan.rows,
                "source_bytes": plan.bytes,
                "already_present": plan.existing,
            }
            for plan in plans
        ]
        verified = tuple(p.name for p in plans if p.existing)
        record["skipped_verified"] = verified
        if args.apply:
            expected = {p.name for p in plans if not p.existing}
            if expected:
                record["status"] = "RUNNING"
                record["partial_changes_possible"] = True
                try:
                    _save_receipt(
                        record, args.evidence_dir
                    )  # No copy without a durable intent.
                except OSError:
                    record["partial_changes_possible"] = False
                    raise
            skipped = copy_missing(client, config, plans, run)
            validated = {
                t.table
                for t in run.tables
                if t.copy_status is Outcome.SUCCESS
                and t.validation_status is Outcome.SUCCESS
            }
            if validated != expected or skipped != verified:
                raise RuntimeError("Missing or inconsistent table-copy outcomes")
            record["skipped_verified"] = skipped
        elif not args.plan and len(verified) != len(plans):
            raise ValueError("Missing destination tables; use --apply to create them")
        record["status"] = "SUCCESS"
        record["partial_changes_possible"] = False
    except Exception as exc:  # noqa: BLE001 - Record unexpected CLI failures without messages.
        failure = exc
        record["status"] = "FAILED"
        record["error_type"] = type(exc).__name__
    finally:
        if args.plan:
            print(
                f"plan: {record['status']} | error={record['error_type']} | {record['tables']}"
            )
        else:
            if run.tables:
                run.finish(error=failure)
                record["copy_run"] = run.to_dict()
            record["finished_at_utc"] = datetime.now(UTC).isoformat()
            try:
                receipt = _save_receipt(record, args.evidence_dir)
            except OSError as exc:
                print(f"receipt: FAILED | error={type(exc).__name__}", file=sys.stderr)
                return 1
            print(
                f"{record['operation']}: {record['status']} | error={record['error_type']} "
                f"| copy_jobs={len(run.tables)} | receipt={receipt}"
            )
    return 0 if record["status"] == "SUCCESS" else 1


if __name__ == "__main__":
    sys.exit(main())
