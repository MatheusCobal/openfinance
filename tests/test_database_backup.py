import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.services.database_backup import backup_sqlite_database, sqlite_database_path


class SQLiteDatabasePathTest(unittest.TestCase):
    def test_relative_sqlite_url_maps_to_file(self):
        self.assertEqual(
            sqlite_database_path("sqlite:///./openfinance.db"),
            Path("./openfinance.db").resolve(),
        )

    def test_absolute_sqlite_url_maps_to_file(self):
        self.assertEqual(
            sqlite_database_path("sqlite:////tmp/openfinance.db"),
            Path("/tmp/openfinance.db").resolve(),
        )

    def test_sqlite_url_with_query_maps_to_file(self):
        self.assertEqual(
            sqlite_database_path("sqlite:///./openfinance.db?timeout=30"),
            Path("./openfinance.db").resolve(),
        )

    def test_memory_sqlite_urls_do_not_map_to_file(self):
        self.assertIsNone(sqlite_database_path("sqlite:///:memory:"))
        self.assertIsNone(sqlite_database_path("sqlite://"))

    def test_non_sqlite_url_does_not_map_to_file(self):
        self.assertIsNone(sqlite_database_path("postgresql://user:pass@localhost/db"))


class SQLiteBackupTest(unittest.TestCase):
    def test_existing_database_is_backed_up_with_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "openfinance.db"
            backup_dir = Path(tmp) / "nested" / "backups"
            with sqlite3.connect(str(db_path)) as connection:
                connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, name TEXT)")
                connection.execute("INSERT INTO sample (name) VALUES ('ok')")

            backup_path = backup_sqlite_database(
                f"sqlite:///{db_path}",
                "snapshot refresh!",
                backup_dir=backup_dir,
                timestamp=datetime(2026, 6, 9, 10, 11, 12, 123456),
            )

            self.assertIsNotNone(backup_path)
            self.assertTrue(backup_dir.exists())
            self.assertTrue(backup_path.exists())
            self.assertEqual(
                backup_path.name,
                "openfinance.20260609-101112-123456.snapshot-refresh.db",
            )
            with sqlite3.connect(str(backup_path)) as connection:
                rows = connection.execute("SELECT name FROM sample").fetchall()
            self.assertEqual(rows, [("ok",)])

    def test_missing_database_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing_path = Path(tmp) / "missing.db"
            backup_dir = Path(tmp) / "backups"

            backup_path = backup_sqlite_database(
                f"sqlite:///{missing_path}",
                "manual",
                backup_dir=backup_dir,
            )

            self.assertIsNone(backup_path)
            self.assertFalse(backup_dir.exists())

    def test_non_file_databases_return_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(
                backup_sqlite_database(
                    "sqlite:///:memory:",
                    "manual",
                    backup_dir=tmp,
                )
            )
            self.assertIsNone(
                backup_sqlite_database(
                    "postgresql://user:pass@localhost/db",
                    "manual",
                    backup_dir=tmp,
                )
            )


class InitDbBackupTest(unittest.TestCase):
    def setUp(self):
        import app.database as database

        self.database = database
        self.previous_startup_backup_done = database._startup_backup_done
        database._startup_backup_done = False

    def tearDown(self):
        self.database._startup_backup_done = self.previous_startup_backup_done

    def test_init_db_backs_up_existing_sqlite_before_alembic_upgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "openfinance.db"
            db_path.touch()
            calls = []

            with (
                patch.object(
                    self.database,
                    "database_settings",
                    SimpleNamespace(database_url=f"sqlite:///{db_path}"),
                ),
                patch.object(self.database, "_alembic_config", return_value="cfg"),
                patch.object(
                    self.database,
                    "backup_sqlite_database",
                    side_effect=lambda *args, **kwargs: calls.append("backup"),
                ) as backup,
                patch.object(
                    self.database,
                    "_prepare_legacy_database_for_alembic",
                    side_effect=lambda *args, **kwargs: calls.append("prepare"),
                ),
                patch.object(
                    self.database.command,
                    "upgrade",
                    side_effect=lambda *args, **kwargs: calls.append("upgrade"),
                ),
            ):
                self.database.init_db()

            backup.assert_called_once_with(f"sqlite:///{db_path}", "alembic-upgrade")
            self.assertEqual(calls, ["backup", "prepare", "upgrade"])

    def test_init_db_does_not_call_backup_for_memory_sqlite(self):
        self._assert_init_db_skips_backup("sqlite:///:memory:")

    def test_init_db_does_not_call_backup_for_non_sqlite(self):
        self._assert_init_db_skips_backup("postgresql://user:pass@localhost/db")

    def _assert_init_db_skips_backup(self, database_url):
        self.database._startup_backup_done = False
        with (
            patch.object(
                self.database,
                "database_settings",
                SimpleNamespace(database_url=database_url),
            ),
            patch.object(self.database, "_alembic_config", return_value="cfg"),
            patch.object(self.database, "backup_sqlite_database") as backup,
            patch.object(self.database, "_prepare_legacy_database_for_alembic"),
            patch.object(self.database.command, "upgrade") as upgrade,
        ):
            self.database.init_db()

        backup.assert_not_called()
        upgrade.assert_called_once_with("cfg", "head")


if __name__ == "__main__":
    unittest.main()
