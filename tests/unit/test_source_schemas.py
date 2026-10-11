"""Failure-oriented unit tests for BigQuery *metadata* contracts; no GCP calls."""

from collections.abc import Callable
from typing import cast

import pytest
from google.cloud import bigquery

from alotech_bi_case_study.contracts.source_schemas import (
    SOURCE_FIELDS,
    SchemaContractError,
    source_schema,
    validate_source_schema,
)

# Independent expected snapshots. Never derive these from SOURCE_FIELDS:
# otherwise an accidental change to the contract can make its tests pass.
# Each value is a sequence of "name TYPE" entries in expected column order.
_EXPECTED: dict[str, str] = {
    "orders": """order_id INTEGER, user_id INTEGER, status STRING, gender STRING,
        created_at TIMESTAMP, returned_at TIMESTAMP, shipped_at TIMESTAMP,
        delivered_at TIMESTAMP, num_of_item INTEGER""",
    "order_items": """id INTEGER, order_id INTEGER, user_id INTEGER,
        product_id INTEGER, inventory_item_id INTEGER, status STRING,
        created_at TIMESTAMP, shipped_at TIMESTAMP, delivered_at TIMESTAMP,
        returned_at TIMESTAMP, sale_price FLOAT""",
    "users": """id INTEGER, first_name STRING, last_name STRING, email STRING,
        age INTEGER, gender STRING, state STRING, street_address STRING,
        postal_code STRING, city STRING, country STRING, latitude FLOAT,
        longitude FLOAT, traffic_source STRING, created_at TIMESTAMP,
        user_geom GEOGRAPHY""",
    "products": """id INTEGER, cost FLOAT, category STRING, name STRING,
        brand STRING, retail_price FLOAT, department STRING, sku STRING,
        distribution_center_id INTEGER""",
}

# A mutation changes only test input, never our actual source contract.
# Callable specifies the mutation signature; `type` is Python 3.13 syntax.
type Mutator = Callable[[list[bigquery.SchemaField]], None]


def _remove_first(fields: list[bigquery.SchemaField]) -> None:
    """Remove a required column from a valid schema."""
    del fields[0]


def _replace_first(fields: list[bigquery.SchemaField], field_type: str) -> None:
    """Inject a bad type into the first column (INTEGER in all four tables)."""
    fields[0] = bigquery.SchemaField(fields[0].name, field_type)


def _replace_mode(fields: list[bigquery.SchemaField]) -> None:
    """Inject an unexpected REPEATED mode into the first column."""
    fields[0] = bigquery.SchemaField(
        fields[0].name, fields[0].field_type, mode="REPEATED"
    )


def _add_nested_field(fields: list[bigquery.SchemaField]) -> None:
    """Inject an unexpected RECORD structure into the first column."""
    fields[0] = bigquery.SchemaField(
        fields[0].name, "RECORD", fields=[bigquery.SchemaField("bad", "STRING")]
    )


def _swap_first_two(fields: list[bigquery.SchemaField]) -> None:
    """Reorder columns without removing or renaming any."""
    fields[0], fields[1] = fields[1], fields[0]


# Each scenario yields a diagnostic substring. All scenarios are run against
# all four tables, not just orders. Anonymous lambdas keep cases compact.
_MUTATIONS: tuple[tuple[str, Mutator, str], ...] = (
    ("missing", _remove_first, "missing column:"),
    (
        "extra",
        lambda f: f.append(bigquery.SchemaField("injected", "STRING")),
        "unexpected column: injected",
    ),
    ("duplicate", lambda f: f.append(f[0]), "duplicate column:"),
    ("wrong-type", lambda f: _replace_first(f, "STRING"), "type mismatch for"),
    ("wrong-mode", _replace_mode, "mode mismatch for"),
    ("reordered", _swap_first_two, "column order differs"),
    ("empty", lambda f: f.clear(), "missing column:"),
    ("nested", _add_nested_field, "unexpected nested fields for"),
)


def test_registered_tables_match_independent_snapshot() -> None:
    """Catch accidental additions/removals from the supported source list."""
    assert set(SOURCE_FIELDS) == set(_EXPECTED)


@pytest.mark.parametrize("table_name", tuple(_EXPECTED))
def test_declared_schema_matches_independent_snapshot(table_name: str) -> None:
    """Catch accidental changes in our definitions, not just validator logic."""
    expected = [
        tuple(item.strip().split()) for item in _EXPECTED[table_name].split(",")
    ]
    actual = source_schema(table_name)
    assert [(f.name, f.field_type) for f in actual] == expected
    assert all(f.mode == "NULLABLE" and not f.fields for f in actual)
    validate_source_schema(table_name, actual)  # Positive control.


@pytest.mark.parametrize("table_name", tuple(_EXPECTED))
@pytest.mark.parametrize(
    ("case", "mutate", "diagnostic"),
    _MUTATIONS,
    ids=[case[0] for case in _MUTATIONS],
)
def test_corrupted_schema_is_rejected(
    table_name: str, case: str, mutate: Mutator, diagnostic: str
) -> None:
    """Inject eight failure modes independently into each of four tables."""
    fields = list(source_schema(table_name))  # Fresh copy: no test leakage.
    mutate(fields)
    with pytest.raises(SchemaContractError) as exc:
        validate_source_schema(table_name, fields)
    assert diagnostic in str(exc.value), case


@pytest.mark.parametrize(
    "bad_name", ["", "orders ", "ORDERS", "unknown", "products.", None, 1, []]
)
def test_unsupported_table_names_are_rejected(bad_name: object) -> None:
    """Reject unsupported strings and incorrectly typed runtime arguments."""
    with pytest.raises(ValueError, match="Unsupported source table"):
        source_schema(cast(str, bad_name))
    with pytest.raises(ValueError, match="Unsupported source table"):
        validate_source_schema(cast(str, bad_name), ())


@pytest.mark.parametrize(
    "invalid", [None, "orders", {"id": "INTEGER"}, ["id"], [None], (42,)]
)
def test_invalid_schema_containers_raise_type_error(invalid: object) -> None:
    """Type hints alone cannot protect callers against malformed runtime input."""
    with pytest.raises(TypeError, match="list or tuple of SchemaField"):
        validate_source_schema("orders", cast(list[bigquery.SchemaField], invalid))


@pytest.mark.parametrize("table_name", tuple(_EXPECTED))
def test_multiple_errors_are_reported_together(table_name: str) -> None:
    """Missing, unexpected, and wrong-mode fields must all appear in one error."""
    fields = list(source_schema(table_name))
    missing = fields.pop(0).name
    fields[0] = bigquery.SchemaField(
        fields[0].name, fields[0].field_type, mode="REQUIRED"
    )
    fields.append(bigquery.SchemaField("injected", "STRING"))
    with pytest.raises(SchemaContractError) as exc:
        validate_source_schema(table_name, fields)
    message = str(exc.value)
    for expected_fragment in (
        f"missing column: {missing}",
        "unexpected column: injected",
        "mode mismatch for",
    ):
        assert expected_fragment in message


@pytest.mark.parametrize("table_name", ("orders", "order_items", "users", "products"))
def test_documented_type_aliases_are_accepted(table_name: str) -> None:
    """Equivalent INT64/FLOAT64 names must not be mistaken for schema drift."""
    aliases = {"INTEGER": "INT64", "FLOAT": "FLOAT64"}
    equivalent = [
        bigquery.SchemaField(
            field.name, aliases.get(field.field_type, field.field_type), mode=field.mode
        )
        for field in source_schema(table_name)
    ]
    validate_source_schema(table_name, equivalent)


def test_noncontract_metadata_does_not_cause_false_rejection() -> None:
    """Descriptions are not part of the enforced source metadata contract."""
    fields = list(source_schema("orders"))
    fields[0] = bigquery.SchemaField(
        fields[0].name, fields[0].field_type, description="Optional note"
    )
    validate_source_schema("orders", fields)


def test_contract_mapping_cannot_be_modified() -> None:
    """Accidental edits to the contract registry fail, even at runtime."""
    with pytest.raises(TypeError):
        cast(dict[str, object], SOURCE_FIELDS)["orders"] = ()
