"""Version-controlled physical schemas for the four thelook_ecommerce sources.

These contracts describe source metadata, *not* PK/FK or row-level quality.
Source columns are all declared NULLABLE, even where data checks require keys.
"""

from collections import Counter
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from google.cloud import bigquery

# Python 3.13's `type` syntax names reusable types without runtime overhead.
type ColumnSpec = tuple[str, str]  # (column name, BigQuery SQL type)
type TableSpec = tuple[ColumnSpec, ...]  # Immutable, ordered columns of one table

# Our source-of-truth snapshot. MappingProxyType prevents dictionary edits;
# tuples prevent edits to the individual table specifications.
SOURCE_FIELDS: Final[Mapping[str, TableSpec]] = MappingProxyType(
    {
        "orders": (
            ("order_id", "INTEGER"),
            ("user_id", "INTEGER"),
            ("status", "STRING"),
            ("gender", "STRING"),
            ("created_at", "TIMESTAMP"),
            ("returned_at", "TIMESTAMP"),
            ("shipped_at", "TIMESTAMP"),
            ("delivered_at", "TIMESTAMP"),
            ("num_of_item", "INTEGER"),
        ),
        "order_items": (
            ("id", "INTEGER"),
            ("order_id", "INTEGER"),
            ("user_id", "INTEGER"),
            ("product_id", "INTEGER"),
            ("inventory_item_id", "INTEGER"),
            ("status", "STRING"),
            ("created_at", "TIMESTAMP"),
            ("shipped_at", "TIMESTAMP"),
            ("delivered_at", "TIMESTAMP"),
            ("returned_at", "TIMESTAMP"),
            ("sale_price", "FLOAT"),
        ),
        "users": (
            ("id", "INTEGER"),
            ("first_name", "STRING"),
            ("last_name", "STRING"),
            ("email", "STRING"),
            ("age", "INTEGER"),
            ("gender", "STRING"),
            ("state", "STRING"),
            ("street_address", "STRING"),
            ("postal_code", "STRING"),
            ("city", "STRING"),
            ("country", "STRING"),
            ("latitude", "FLOAT"),
            ("longitude", "FLOAT"),
            ("traffic_source", "STRING"),
            ("created_at", "TIMESTAMP"),
            ("user_geom", "GEOGRAPHY"),
        ),
        "products": (
            ("id", "INTEGER"),
            ("cost", "FLOAT"),
            ("category", "STRING"),
            ("name", "STRING"),
            ("brand", "STRING"),
            ("retail_price", "FLOAT"),
            ("department", "STRING"),
            ("sku", "STRING"),
            ("distribution_center_id", "INTEGER"),
        ),
    }
)

# GoogleSQL has equivalent type spellings, these should not cause false drift.
_TYPE_ALIASES: Final[Mapping[str, str]] = MappingProxyType(
    {"INT64": "INTEGER", "FLOAT64": "FLOAT", "BOOL": "BOOLEAN"}
)


class SchemaContractError(ValueError):
    """The observed BigQuery schema differs from the declared source contract."""


def source_schema(table_name: str) -> tuple[bigquery.SchemaField, ...]:
    """Build SDK schema objects for an approved source table.

    Returns a new tuple of SchemaField objects on each call. Rejects unknown
    or malformed table names with a predictable ValueError.
    """
    # Check the type *before* dictionary lookup: an unexpected list would
    # otherwise cause an unrelated 'unhashable type' exception.
    if not isinstance(table_name, str) or table_name not in SOURCE_FIELDS:
        raise ValueError(f"Unsupported source table: {table_name!r}")

    # Preserve the exact declared column order and NULLABLE source modes.
    return tuple(
        bigquery.SchemaField(name, field_type, mode="NULLABLE")
        for name, field_type in SOURCE_FIELDS[table_name]
    )


def _canonical_type(field_type: str) -> str:
    """Normalize documented type aliases, without coercing incompatible types."""
    upper = field_type.upper()
    return _TYPE_ALIASES.get(upper, upper)


def validate_source_schema(
    table_name: str,
    actual_schema: list[bigquery.SchemaField] | tuple[bigquery.SchemaField, ...],
) -> None:
    """Reject missing, extra, duplicated, reordered or changed source columns.

    Checks names, types, modes, and unexpected nesting. Ignores field
    descriptions and other optional metadata. Collects multiple violations
    into one SchemaContractError to help diagnose upstream schema drift.

    A successful return means *metadata* matched; it says nothing about rows.
    """
    expected = source_schema(table_name)  # Also validates table_name.

    # Reject incorrect runtime objects explicitly, despite static type hints.
    if not isinstance(actual_schema, (list, tuple)) or not all(
        isinstance(field, bigquery.SchemaField) for field in actual_schema
    ):
        raise TypeError("actual_schema must be a list or tuple of SchemaField")

    # Names are checked separately from types so errors are actionable.
    expected_by_name = {field.name: field for field in expected}
    expected_names = [field.name for field in expected]
    actual_names = [field.name for field in actual_schema]
    actual_counts = Counter(actual_names)
    problems: list[str] = []  # Multiple problems reported in one exception.

    for name in expected_names:
        if name not in actual_counts:
            problems.append(f"missing column: {name}")

    for name, count in actual_counts.items():
        if name not in expected_by_name:
            problems.append(f"unexpected column: {name}")
        if count > 1:
            problems.append(f"duplicate column: {name}")

    # Deliberately strict: a reordered snapshot is drift, even with same names.
    if actual_names != expected_names:
        problems.append("column order differs from contract")

    for field in actual_schema:
        reference = expected_by_name.get(field.name)
        if reference is None:  # Already reported as an unexpected column.
            continue

        if _canonical_type(field.field_type) != _canonical_type(reference.field_type):
            problems.append(
                f"type mismatch for {field.name}: "
                f"expected {reference.field_type}, got {field.field_type}"
            )
        if field.mode != reference.mode:
            problems.append(
                f"mode mismatch for {field.name}: "
                f"expected {reference.mode}, got {field.mode}"
            )
        if field.fields:  # All four observed schemas are flat, never RECORD.
            problems.append(f"unexpected nested fields for {field.name}")

    if problems:
        raise SchemaContractError(
            f"Schema validation failed for {table_name}: " + "; ".join(problems)
        )
