"""Release migrations stay outside the API and worker runtime roles."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from scripts import migrate_database


class DatabaseMigrationTests(unittest.TestCase):
    def test_migrations_require_the_dedicated_migrator_process_role(self):
        settings = SimpleNamespace(
            PROCESS_ROLE="api",
            RUNTIME_SCHEMA_DDL_ENABLED=False,
            ENVIRONMENT="shadow",
            MYSQL_MIGRATOR_USER="schema-migrator",
        )
        with patch.object(migrate_database, "settings", settings):
            with self.assertRaisesRegex(RuntimeError, "PROCESS_ROLE=migrator"):
                migrate_database._validate_invocation()

    def test_migrations_reject_runtime_ddl_even_for_migrator(self):
        settings = SimpleNamespace(
            PROCESS_ROLE="migrator",
            RUNTIME_SCHEMA_DDL_ENABLED=True,
            ENVIRONMENT="shadow",
            MYSQL_MIGRATOR_USER="schema-migrator",
        )
        with patch.object(migrate_database, "settings", settings):
            with self.assertRaisesRegex(RuntimeError, "must remain false"):
                migrate_database._validate_invocation()

    def test_apply_records_the_migration_once_and_releases_the_lock(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = (1,)
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        connection.__enter__.return_value = connection
        connection.__exit__.return_value = False

        with (
            patch.object(migrate_database, "_validate_invocation"),
            patch.object(migrate_database, "mysql_connection", return_value=connection),
            patch.object(migrate_database, "_ensure_ledger"),
            patch.object(migrate_database, "_is_applied", return_value=False),
            patch.object(migrate_database, "_apply_initial_schema") as apply_schema,
            patch.object(
                migrate_database,
                "_apply_idempotent_job_effects_schema",
            ) as apply_effects_schema,
            patch.object(
                migrate_database,
                "_apply_publication_guard_schema",
            ) as apply_publication_schema,
            patch.object(migrate_database, "_missing_runtime_tables", return_value=[]),
        ):
            result = migrate_database.apply_migrations()

        self.assertEqual(
            result["applied"],
            list(migrate_database.REQUIRED_MIGRATIONS),
        )
        apply_schema.assert_called_once_with()
        apply_effects_schema.assert_called_once_with()
        apply_publication_schema.assert_called_once_with()
        executed = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertTrue(any("GET_LOCK" in statement for statement in executed))
        self.assertTrue(any("INSERT INTO schema_migrations" in statement for statement in executed))
        self.assertTrue(any("RELEASE_LOCK" in statement for statement in executed))

    def test_apply_is_idempotent_after_the_initial_schema_exists(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = (1,)
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        connection.__enter__.return_value = connection
        connection.__exit__.return_value = False

        with (
            patch.object(migrate_database, "_validate_invocation"),
            patch.object(migrate_database, "mysql_connection", return_value=connection),
            patch.object(migrate_database, "_ensure_ledger"),
            patch.object(migrate_database, "_is_applied", return_value=True),
            patch.object(migrate_database, "_apply_initial_schema") as apply_schema,
            patch.object(
                migrate_database,
                "_apply_idempotent_job_effects_schema",
            ) as apply_effects_schema,
            patch.object(
                migrate_database,
                "_apply_publication_guard_schema",
            ) as apply_publication_schema,
            patch.object(migrate_database, "_missing_runtime_tables", return_value=[]),
        ):
            result = migrate_database.apply_migrations()

        self.assertEqual(
            result["already_applied"],
            list(migrate_database.REQUIRED_MIGRATIONS),
        )
        apply_schema.assert_not_called()
        apply_effects_schema.assert_not_called()
        apply_publication_schema.assert_not_called()

    def test_check_rejects_a_partial_schema_even_with_a_migration_ledger(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.__exit__.return_value = False
        with (
            patch.object(migrate_database, "_validate_invocation"),
            patch.object(migrate_database, "mysql_connection", return_value=connection),
            patch.object(migrate_database, "_ensure_ledger"),
            patch.object(migrate_database, "_is_applied", return_value=True),
            patch.object(
                migrate_database,
                "_missing_runtime_tables",
                return_value=["incident_jobs"],
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "runtime schema is incomplete"):
                migrate_database.check_migrations()
