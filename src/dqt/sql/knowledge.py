"""Reference data a column's values must come from (Knowledge/Domain facet).

The facet in ``docs/CONVENTIONS-DQT.md`` §2 that had no module behind it.
``docs/API-STABILITY.md`` names it a ``1.0.0`` blocker: freezing a public API
while the facet table still reads "not started" would mean either adding to a
frozen surface afterwards, or admitting the model overstated what DQT does.

A **reference set** is the authoritative list of values a column may hold --
a currency table, a chart of accounts, the branches of a bank. Checking a
column against one is a validity check, and it is the check neither ``regex``
nor ``RANGE`` can express: membership of a set that lives in the data rather
than in a pattern.

Two sources, because two situations are genuinely different:

* :class:`ReferenceTable` -- a table in the same database. The check compiles
  to an anti-join, so matching a hundred-million-row table against its
  reference is the query planner's problem, not Python's.
* :class:`ReferenceList` -- values written inline in the rule file, for a
  vocabulary small enough to read there. Bound as parameters, never
  interpolated: ``DQT-02`` parameterised rule literals because they come from
  a file a person edits, and a reference value comes from the same file.

**DQT ships no reference data.** A data-quality tool that carries its own
country list is one stale release away from reporting correct data as
invalid, and a false positive on a clean table costs more trust than the
convenience is worth. DQT provides the mechanism; the DBA provides the
authority.

Example:
    from dqt.sql.knowledge import ReferenceTable, unmatched_count_query

    reference = ReferenceTable(table_name="ref_cities", column_name="name")
    sql, binds = unmatched_count_query(dialect, None, "people", "city", reference)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dqt.classification import PERSIAN_FOLD_RULES
from dqt.sql._identifiers import qualified_identifier, quote_identifier
from dqt.sql.dialects.base import Dialect

__all__ = [
    "ReferenceList",
    "ReferenceSet",
    "ReferenceTable",
    "persian_fold_expression",
    "reference_set_from_params",
    "unmatched_count_query",
]


@dataclass(frozen=True, slots=True)
class ReferenceList:
    """Allowed values written inline in a rule file.

    Attributes:
        values: The allowed values, in the order written. Never empty --
            :func:`reference_set_from_params` refuses an empty set, because
            it would make every value a violation.

    Example:
        reference = ReferenceList(values=("OPEN", "CLOSED"))
    """

    values: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReferenceTable:
    """Allowed values held in a table of the same database.

    Attributes:
        table_name: The reference table.
        column_name: The column holding the allowed values.
        schema_name: Schema qualifier, or None. Reference data usually does
            not sit beside the data it governs.

    Example:
        reference = ReferenceTable(table_name="ref_cities", column_name="name")
    """

    table_name: str
    column_name: str
    schema_name: str | None = None


#: Either source of allowed values.
ReferenceSet = ReferenceList | ReferenceTable


def reference_set_from_params(params: dict[str, Any]) -> ReferenceSet:
    """Read a reference set out of a rule's parameters.

    Args:
        params: The rule's ``params`` mapping.

    Returns:
        The :class:`ReferenceList` or :class:`ReferenceTable` it describes.

    Raises:
        ValueError: If it names neither source, both, an empty list, or a
            table without its column. Every one of those is a configuration
            mistake whose silent reading would produce a wrong answer rather
            than no answer.

    Example:
        reference = reference_set_from_params({"values": ["OPEN"]})
    """
    values = params.get("values")
    table_name = params.get("reference_table")

    if values is not None and table_name is not None:
        raise ValueError(
            "A REFERENCE rule names both 'values' and 'reference_table'. Only "
            "one can be the authority on what a column is allowed to hold, and "
            "DQT will not choose. Remove whichever is not intended."
        )
    if values is None and table_name is None:
        raise ValueError(
            "A REFERENCE rule needs somewhere to look: give it 'values' (an "
            "inline list) or 'reference_table' with 'reference_column' (a "
            "table in the same database). Without one, the rule would report "
            "a clean column it never actually checked."
        )

    if table_name is not None:
        column_name = params.get("reference_column")
        if not column_name:
            raise ValueError(
                f"A REFERENCE rule names reference_table {table_name!r} but no "
                "'reference_column'. A table is not a set of values until one "
                "of its columns is named."
            )
        return ReferenceTable(
            table_name=str(table_name),
            column_name=str(column_name),
            schema_name=params.get("reference_schema"),
        )

    if not values:
        raise ValueError(
            "A REFERENCE rule's 'values' list is empty, which would make every "
            "non-NULL value a violation. That is far more likely to be a "
            "configuration that failed to load than a deliberate rule."
        )
    return ReferenceList(values=tuple(str(value) for value in values))


def persian_fold_expression(quoted_expression: str) -> str:
    """Wrap *quoted_expression* in the SQL form of the Persian fold.

    The fold is :func:`dqt.classification.normalize_persian_text`, pushed
    into SQL as nested ``REPLACE`` calls so the comparison still happens in
    the database. Doing it in Python would mean reading every value out to
    compare it, which is the thing DQT exists not to do.

    Args:
        quoted_expression: An already-quoted column reference or expression.

    Returns:
        The wrapped expression.

    Example:
        assert persian_fold_expression('"c"').startswith("REPLACE(")
    """
    folded = quoted_expression
    for source, replacement in PERSIAN_FOLD_RULES:
        folded = f"REPLACE({folded}, '{source}', '{replacement}')"
    return folded


def unmatched_count_query(
    dialect: Dialect,
    schema_name: str | None,
    table_name: str,
    column_name: str,
    reference: ReferenceSet,
    *,
    normalize_persian: bool = False,
) -> tuple[str, tuple[Any, ...]]:
    """Build the single query that counts values absent from *reference*.

    Two aggregates in one pass: how many non-NULL values were checked, and
    how many of them were not found. A NULL is "not applicable" rather than
    "invalid" -- the reading ``regex_not_matching_predicate`` already takes
    -- so NULLs are excluded rather than counted as violations.

    Args:
        dialect: Dialect supplying quoting and the bind placeholder.
        schema_name: Schema of the table under test, or None.
        table_name: Table under test.
        column_name: Column under test.
        reference: Where the allowed values come from.
        normalize_persian: Fold Persian and Arabic letter variants on both
            sides before comparing. Off by default: changing values silently
            is not a data-quality tool's job.

    Returns:
        The statement and its bind values, in placeholder order.

    Example:
        sql, binds = unmatched_count_query(dialect, None, "t", "c", reference)
    """
    table = qualified_identifier(schema_name, table_name)
    column = f"{table}.{quote_identifier(column_name)}"
    compared_column = persian_fold_expression(column) if normalize_persian else column

    if isinstance(reference, ReferenceList):
        placeholders = ", ".join([dialect.parameter_placeholder] * len(reference.values))
        # The values are folded in Python rather than in SQL: they are known
        # here, so wrapping each placeholder in twenty-odd REPLACE calls would
        # ask the database to compute a constant.
        binds = tuple(
            _folded_in_python(value) if normalize_persian else value for value in reference.values
        )
        return (
            dialect.select_aggregates_sql(
                table,
                [
                    f"COUNT({column})",
                    f"SUM(CASE WHEN {compared_column} NOT IN ({placeholders}) THEN 1 ELSE 0 END)",
                ],
                f"{column} IS NOT NULL",
            ),
            binds,
        )

    reference_table = qualified_identifier(reference.schema_name, reference.table_name)
    reference_column = f"{reference_table}.{quote_identifier(reference.column_name)}"
    compared_reference = (
        persian_fold_expression(reference_column) if normalize_persian else reference_column
    )
    # The join is expressed as the table reference so the whole statement stays
    # one call to the dialect: an already-quoted FROM clause is what
    # select_aggregates_sql takes, and a join is a table reference.
    joined = f"{table} LEFT JOIN {reference_table} ON {compared_column} = {compared_reference}"
    return (
        dialect.select_aggregates_sql(
            joined,
            [
                f"COUNT({column})",
                f"SUM(CASE WHEN {reference_column} IS NULL THEN 1 ELSE 0 END)",
            ],
            f"{column} IS NOT NULL",
        ),
        (),
    )


def _folded_in_python(value: str) -> str:
    """Apply the Persian fold to a value already known to DQT.

    Args:
        value: The reference value as written in the rule file.

    Returns:
        The folded value.

    Example:
        assert _folded_in_python("شيراز") == "شیراز"
    """
    folded = value
    for source, replacement in PERSIAN_FOLD_RULES:
        folded = folded.replace(source, replacement)
    return folded
