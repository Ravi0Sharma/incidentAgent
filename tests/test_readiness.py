"""Readiness must observe the runtime database without mutating it."""

import unittest
from unittest.mock import patch

from webhook import incident_store


class _Cursor:
    def __init__(self, rows):
        self.rows = iter(rows)
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, statement, parameters=None):
        self.statements.append((statement, parameters))

    def fetchone(self):
        return next(self.rows)


class _Connection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True


class ReadinessTests(unittest.TestCase):
    def test_readiness_checks_schema_without_runtime_ddl_or_writes(self):
        cursor = _Cursor(rows=[(1,), (1,)])
        connection = _Connection(cursor)
        with (
            patch.object(incident_store, "_connection", return_value=connection),
            patch.object(incident_store, "ensure_schema") as ensure_schema,
        ):
            result = incident_store.readiness_check()

        self.assertEqual(result["database"], "ready")
        self.assertEqual(result["queue"], "ready")
        self.assertEqual(result["schema"], "ready")
        ensure_schema.assert_not_called()
        self.assertFalse(connection.committed)
        statements = "\n".join(statement for statement, _ in cursor.statements).upper()
        self.assertNotRegex(statements, r"\b(CREATE|ALTER|INSERT|UPDATE|DELETE)\b")

    def test_worker_readiness_also_avoids_schema_initialization(self):
        cursor = _Cursor(rows=[(1,), (1,), (0, None)])
        with (
            patch.object(
                incident_store,
                "_connection",
                return_value=_Connection(cursor),
            ),
            patch.object(incident_store, "ensure_schema") as ensure_schema,
        ):
            result = incident_store.readiness_check(require_worker=True)

        self.assertEqual(result["worker"]["status"], "unavailable")
        ensure_schema.assert_not_called()

    def test_readiness_rejects_a_database_without_the_runtime_schema(self):
        cursor = _Cursor(rows=[(1,), None])
        with patch.object(
            incident_store,
            "_connection",
            return_value=_Connection(cursor),
        ):
            result = incident_store.readiness_check()

        self.assertEqual(result["database"], "ready")
        self.assertEqual(result["queue"], "unavailable")
        self.assertEqual(result["schema"], "missing")
