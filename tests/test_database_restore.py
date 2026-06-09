import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.services.database_restore import (
    RestoreError,
    RestoreResult,
    restore_sqlite_database,
    validate_sqlite_database,
)


def _make_db(path: Path, value: str = "original") -> None:
    with sqlite3.connect(str(path)) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS t (v TEXT)")
        conn.execute("INSERT INTO t VALUES (?)", (value,))


def _read_db(path: Path) -> list[str]:
    with sqlite3.connect(str(path)) as conn:
        return [row[0] for row in conn.execute("SELECT v FROM t").fetchall()]


class ValidateSQLiteDatabaseTest(unittest.TestCase):
    def test_valid_sqlite_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "valid.db"
            _make_db(path, "data")
            validate_sqlite_database(path)  # must not raise

    def test_missing_file_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.db"
            with self.assertRaises(RestoreError) as ctx:
                validate_sqlite_database(missing)
            self.assertIn("not found", str(ctx.exception).lower())

    def test_non_sqlite_file_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notdb.db"
            path.write_bytes(b"this is not a sqlite database")
            with self.assertRaises(RestoreError):
                validate_sqlite_database(path)

    def test_corrupted_file_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "corrupt.db"
            # Write a file with the SQLite magic header followed by garbage
            path.write_bytes(b"SQLite format 3\x00" + b"\xff" * 200)
            with self.assertRaises(RestoreError):
                validate_sqlite_database(path)


class RestoreSQLiteDatabaseTest(unittest.TestCase):
    def test_round_trip_restore(self):
        """Backup a DB, modify original, restore from backup — data must match backup."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "openfinance.db"
            backup_dir = Path(tmp) / "backups"
            _make_db(db_path, "before-backup")

            database_url = f"sqlite:///{db_path}"
            from app.services.database_backup import backup_sqlite_database

            backup_path = backup_sqlite_database(database_url, "test", backup_dir=backup_dir)

            # Modify the original
            with sqlite3.connect(str(db_path)) as conn:
                conn.execute("INSERT INTO t VALUES (?)", ("after-backup",))

            self.assertEqual(_read_db(db_path), ["before-backup", "after-backup"])

            result = restore_sqlite_database(database_url, backup_path, backup_dir=backup_dir)

            self.assertIsInstance(result, RestoreResult)
            self.assertEqual(_read_db(db_path), ["before-backup"])

    def test_restore_creates_pre_restore_backup(self):
        """When destination exists, a pre-restore backup is created with the old content."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "openfinance.db"
            backup_dir = Path(tmp) / "backups"
            _make_db(db_path, "current-state")

            database_url = f"sqlite:///{db_path}"
            from app.services.database_backup import backup_sqlite_database

            backup_path = backup_sqlite_database(database_url, "test", backup_dir=backup_dir)

            # Replace the current db content so pre-restore backup captures it
            with sqlite3.connect(str(db_path)) as conn:
                conn.execute("INSERT INTO t VALUES (?)", ("modified",))

            result = restore_sqlite_database(database_url, backup_path, backup_dir=backup_dir)

            self.assertIsNotNone(result.pre_restore_backup)
            self.assertTrue(result.pre_restore_backup.exists())
            # Pre-restore backup must contain the modified state
            self.assertIn("modified", _read_db(result.pre_restore_backup))

    def test_invalid_backup_fails_before_overwriting(self):
        """A non-SQLite backup file must not overwrite the destination."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "openfinance.db"
            backup_dir = Path(tmp) / "backups"
            _make_db(db_path, "safe-data")

            bad_backup = Path(tmp) / "bad.db"
            bad_backup.write_bytes(b"not a sqlite file at all")

            database_url = f"sqlite:///{db_path}"
            with self.assertRaises(RestoreError):
                restore_sqlite_database(database_url, bad_backup, backup_dir=backup_dir)

            # Original must be untouched
            self.assertEqual(_read_db(db_path), ["safe-data"])

    def test_corrupted_backup_fails_before_overwriting(self):
        """A backup with the SQLite header but corrupted body must not overwrite destination."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "openfinance.db"
            backup_dir = Path(tmp) / "backups"
            _make_db(db_path, "safe-data")

            corrupt_backup = Path(tmp) / "corrupt.db"
            corrupt_backup.write_bytes(b"SQLite format 3\x00" + b"\xff" * 200)

            database_url = f"sqlite:///{db_path}"
            with self.assertRaises(RestoreError):
                restore_sqlite_database(database_url, corrupt_backup, backup_dir=backup_dir)

            self.assertEqual(_read_db(db_path), ["safe-data"])

    def test_restore_when_destination_does_not_exist(self):
        """When destination does not exist, restore creates it with no pre-restore backup."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "new_openfinance.db"
            backup_dir = Path(tmp) / "backups"

            # Create a backup from a different source db
            source_db = Path(tmp) / "source.db"
            _make_db(source_db, "seeded")
            from app.services.database_backup import backup_sqlite_database

            backup_path = backup_sqlite_database(
                f"sqlite:///{source_db}", "test", backup_dir=backup_dir
            )

            database_url = f"sqlite:///{db_path}"
            result = restore_sqlite_database(database_url, backup_path, backup_dir=backup_dir)

            self.assertIsNone(result.pre_restore_backup)
            self.assertTrue(db_path.exists())
            self.assertEqual(_read_db(db_path), ["seeded"])

    def test_non_sqlite_database_url_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_backup = Path(tmp) / "backup.db"
            _make_db(fake_backup)
            with self.assertRaises(RestoreError) as ctx:
                restore_sqlite_database("postgresql://user:pass@localhost/db", fake_backup)
            self.assertIn("file-based SQLite", str(ctx.exception))

    def test_memory_sqlite_url_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_backup = Path(tmp) / "backup.db"
            _make_db(fake_backup)
            with self.assertRaises(RestoreError) as ctx:
                restore_sqlite_database("sqlite:///:memory:", fake_backup)
            self.assertIn("file-based SQLite", str(ctx.exception))

    def test_restore_does_not_delete_backup_source(self):
        """The backup file used as source must still exist after a successful restore."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "openfinance.db"
            backup_dir = Path(tmp) / "backups"
            _make_db(db_path, "data")

            database_url = f"sqlite:///{db_path}"
            from app.services.database_backup import backup_sqlite_database

            backup_path = backup_sqlite_database(database_url, "test", backup_dir=backup_dir)

            restore_sqlite_database(database_url, backup_path, backup_dir=backup_dir)

            self.assertTrue(backup_path.exists())

    def test_atomic_restore_no_temp_file_left_on_success(self):
        """After a successful restore, no .restore-tmp file should remain."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "openfinance.db"
            backup_dir = Path(tmp) / "backups"
            _make_db(db_path, "data")

            database_url = f"sqlite:///{db_path}"
            from app.services.database_backup import backup_sqlite_database

            backup_path = backup_sqlite_database(database_url, "test", backup_dir=backup_dir)
            restore_sqlite_database(database_url, backup_path, backup_dir=backup_dir)

            tmp_path = db_path.with_suffix(".restore-tmp.db")
            self.assertFalse(tmp_path.exists())

    def test_missing_backup_file_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "openfinance.db"
            _make_db(db_path, "data")
            missing = Path(tmp) / "no_such_backup.db"
            with self.assertRaises(RestoreError) as ctx:
                restore_sqlite_database(f"sqlite:///{db_path}", missing)
            self.assertIn("not found", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
