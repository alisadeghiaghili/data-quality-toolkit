"""``_json_safe_metadata_value``: making a raw driver value JSON-native (`NEW-AF`).

``ColumnProfile.min_value``/``max_value`` carry whatever the DBAPI driver
returned for ``MIN``/``MAX`` -- a :class:`decimal.Decimal` for
``numeric``/``money`` on ``psycopg`` and ``pyodbc``, a
:class:`datetime.date`/:class:`~datetime.datetime`/:class:`~datetime.time`
for a temporal column, raw ``bytes`` for a binary one, or a
:class:`uuid.UUID` for ``uuid``/``uniqueidentifier``. None of those survive
:func:`json.dumps` without a ``default``, so
:meth:`~dqt.sql.profiling.SqlProfiler.build_metrics` runs every profiled
bound through this helper before it goes into a :class:`~dqt.common.models.DQMetric`.

Every expected value below is derived by hand from the type's own
conversion rule (``str()`` for a Decimal, ``isoformat()`` for a date/time,
hex for bytes), never by running the function and asserting it equals
itself.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal

from dqt.sql.profiling import _json_safe_metadata_value


class TestValuesThatAreAlreadyJsonNative:
    """None of these should be touched at all."""

    def test_none_passes_through(self):
        assert _json_safe_metadata_value(None) is None

    def test_bool_passes_through(self):
        assert _json_safe_metadata_value(True) is True

    def test_int_passes_through(self):
        assert _json_safe_metadata_value(42) == 42

    def test_float_passes_through(self):
        assert _json_safe_metadata_value(3.5) == 3.5

    def test_str_passes_through(self):
        assert _json_safe_metadata_value("ali") == "ali"


class TestDecimal:
    def test_exact_digits_are_preserved_as_a_string(self):
        # str(Decimal("12.50")) == "12.50": the trailing zero is part of the
        # decimal's own precision, and it must survive -- float("12.50")
        # would silently lose it (12.5).
        assert _json_safe_metadata_value(Decimal("12.50")) == "12.50"

    def test_a_value_float_would_round_differently_stays_exact(self):
        assert _json_safe_metadata_value(Decimal("19.999999999999999")) == "19.999999999999999"


class TestDateAndTime:
    def test_date_becomes_iso_8601(self):
        assert _json_safe_metadata_value(date(2024, 1, 2)) == "2024-01-02"

    def test_datetime_becomes_iso_8601(self):
        assert _json_safe_metadata_value(datetime(2024, 1, 2, 10, 30, 0)) == "2024-01-02T10:30:00"

    def test_time_becomes_iso_8601(self):
        assert _json_safe_metadata_value(time(10, 30, 0)) == "10:30:00"


class TestBinaryValues:
    """Bounded, hex-encoded, and marked when truncated."""

    def test_short_bytes_become_a_full_hex_preview(self):
        # b"\x00\xff" is two bytes, well under the 32-byte bound: the whole
        # value is shown, with no truncation marker.
        assert _json_safe_metadata_value(b"\x00\xff") == "0x00ff"

    def test_exactly_32_bytes_carries_no_truncation_marker(self):
        # The boundary itself: 32 bytes of 0x41 ("A"), hex-encoded is 64
        # hex digits, with nothing appended.
        value = b"\x41" * 32
        expected = "0x" + ("41" * 32)
        assert _json_safe_metadata_value(value) == expected
        assert "…" not in _json_safe_metadata_value(value)

    def test_33_bytes_is_truncated_to_32_with_a_marker(self):
        # One byte past the bound: the preview shows only the first 32
        # bytes' hex (64 hex digits) and appends the ellipsis marker.
        value = b"\x41" * 33
        expected = "0x" + ("41" * 32) + "…"
        assert _json_safe_metadata_value(value) == expected

    def test_bytearray_is_handled_the_same_as_bytes(self):
        assert _json_safe_metadata_value(bytearray(b"\x00\xff")) == "0x00ff"

    def test_memoryview_is_handled_the_same_as_bytes(self):
        assert _json_safe_metadata_value(memoryview(b"\x00\xff")) == "0x00ff"


class TestUuidAndFallback:
    def test_uuid_becomes_its_string_form(self):
        value = uuid.UUID("a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11")
        assert _json_safe_metadata_value(value) == "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"

    def test_an_unrecognised_type_falls_back_to_str(self):
        class Unrecognised:
            def __str__(self) -> str:
                return "unrecognised-value"

        assert _json_safe_metadata_value(Unrecognised()) == "unrecognised-value"
