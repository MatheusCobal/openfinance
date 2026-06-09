import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app.services.database_backup import prune_sqlite_backups


def _make_backup(backup_dir: Path, stem: str, ts: datetime, reason: str = "test") -> Path:
    """Create a minimal synthetic backup file with the app's naming convention."""
    filename = f"{stem}.{ts.strftime('%Y%m%d-%H%M%S-%f')}.{reason}.db"
    path = backup_dir / filename
    with sqlite3.connect(str(path)) as conn:
        conn.execute("CREATE TABLE t (v TEXT)")
    return path


class PruneSQLiteBackupsTest(unittest.TestCase):
    def test_nonexistent_dir_returns_empty(self):
        result = prune_sqlite_backups("/tmp/no_such_dir_xyz_openfinance_test")
        self.assertEqual(result, [])

    def test_fewer_than_keep_last_removes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            backup_dir = Path(tmp)
            for i in range(5):
                _make_backup(backup_dir, "db", datetime(2026, 1, i + 1, 10, 0, 0), "test")

            deleted = prune_sqlite_backups(backup_dir, keep_last=14)
            self.assertEqual(deleted, [])
            self.assertEqual(len(list(backup_dir.iterdir())), 5)

    def test_more_than_keep_last_removes_oldest(self):
        with tempfile.TemporaryDirectory() as tmp:
            backup_dir = Path(tmp)
            created = []
            for i in range(20):
                p = _make_backup(backup_dir, "db", datetime(2026, 1, i + 1, 10, 0, 0), "test")
                created.append(p)

            deleted = prune_sqlite_backups(backup_dir, keep_last=14, keep_monthly=False)

            # Exactly 6 should be deleted (20 - 14)
            self.assertEqual(len(deleted), 6)
            # The deleted ones must be the oldest
            for removed in deleted:
                self.assertIn(removed, created[:6])
            # The kept ones must all exist
            for kept in created[6:]:
                self.assertTrue(kept.exists())

    def test_keep_monthly_preserves_first_of_each_month(self):
        with tempfile.TemporaryDirectory() as tmp:
            backup_dir = Path(tmp)
            # 5 backups in January, 5 in February, 1 in June — 11 total
            # Sorted chronologically: Jan1..5, Feb1..5, Jun1
            jan = [
                _make_backup(backup_dir, "db", datetime(2025, 1, d, 10, 0, 0), "test")
                for d in range(1, 6)
            ]
            feb = [
                _make_backup(backup_dir, "db", datetime(2025, 2, d, 10, 0, 0), "test")
                for d in range(1, 6)
            ]
            jun = _make_backup(backup_dir, "db", datetime(2026, 6, 1, 10, 0, 0), "test")

            # keep_last=3 → keeps Feb4, Feb5, Jun1 (the 3 most recent)
            # keep_monthly → also keeps Jan1 (first of Jan) and Feb1 (first of Feb)
            # keep set: {Jan1, Feb1, Feb4, Feb5, Jun1} = 5 files → 6 deleted out of 11
            deleted = prune_sqlite_backups(backup_dir, keep_last=3, keep_monthly=True)

            # Monthly firsts must be preserved
            self.assertTrue(jan[0].exists(), "first-of-January backup was deleted")
            self.assertTrue(feb[0].exists(), "first-of-February backup was deleted")
            self.assertTrue(jun.exists(), "June backup was deleted")
            # The most recent 3 must be preserved (Feb4=feb[3], Feb5=feb[4], Jun1)
            self.assertTrue(feb[3].exists(), "Feb4 backup was deleted (in keep_last)")
            self.assertTrue(feb[4].exists(), "Feb5 backup was deleted (in keep_last)")
            # Everything else deleted: Jan2,3,4,5 + Feb2,3 = 6
            self.assertEqual(len(deleted), 6)

    def test_files_outside_pattern_are_not_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            backup_dir = Path(tmp)
            # App-generated backups (20 of them — more than keep_last=14)
            for i in range(20):
                _make_backup(backup_dir, "db", datetime(2026, 1, i + 1, 10, 0, 0), "test")

            # Files NOT matching the app pattern
            old_format = backup_dir / "openfinance-2026-06-02-105504.db"
            old_format.write_bytes(b"")
            manual_copy = backup_dir / "my-manual-copy.db"
            manual_copy.write_bytes(b"")
            readme = backup_dir / "README.txt"
            readme.write_text("notes")

            prune_sqlite_backups(backup_dir, keep_last=14, keep_monthly=False)

            # Non-pattern files must survive
            self.assertTrue(old_format.exists())
            self.assertTrue(manual_copy.exists())
            self.assertTrue(readme.exists())

    def test_temp_files_are_not_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            backup_dir = Path(tmp)
            # Create many app backups to trigger pruning
            for i in range(20):
                _make_backup(backup_dir, "db", datetime(2026, 1, i + 1, 10, 0, 0), "test")

            # A restore-tmp file should never be pruned
            tmp_file = backup_dir / "db.20260101-120000-000000.restore-tmp.db"
            tmp_file.write_bytes(b"")

            prune_sqlite_backups(backup_dir, keep_last=14, keep_monthly=False)

            self.assertTrue(tmp_file.exists())

    def test_prune_only_cli_flag(self):
        """--prune-only prunes without creating a new backup."""
        with tempfile.TemporaryDirectory() as tmp:
            backup_dir = Path(tmp) / "backups"
            backup_dir.mkdir()

            # Create a database and 20 backup files
            db_path = Path(tmp) / "openfinance.db"
            with sqlite3.connect(str(db_path)) as conn:
                conn.execute("CREATE TABLE t (v TEXT)")

            for i in range(20):
                _make_backup(backup_dir, "openfinance", datetime(2026, 1, i + 1, 10, 0, 0), "test")

            count_before = len(list(backup_dir.iterdir()))
            self.assertEqual(count_before, 20)

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/backup_database.py",
                    "--prune-only",
                    "--keep-last",
                    "14",
                    "--no-keep-monthly",
                    "--backup-dir",
                    str(backup_dir),
                ],
                capture_output=True,
                text=True,
                cwd=Path(__file__).resolve().parents[1],
                env={
                    **__import__("os").environ,
                    "DATABASE_URL": f"sqlite:///{db_path}",
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            count_after = len(list(backup_dir.iterdir()))
            self.assertEqual(count_after, 14)

    def test_prune_flag_after_backup(self):
        """--prune removes old backups after creating a new one."""
        with tempfile.TemporaryDirectory() as tmp:
            backup_dir = Path(tmp) / "backups"
            backup_dir.mkdir()

            db_path = Path(tmp) / "openfinance.db"
            with sqlite3.connect(str(db_path)) as conn:
                conn.execute("CREATE TABLE t (v TEXT)")

            # Pre-populate with 14 old backups
            for i in range(14):
                _make_backup(backup_dir, "openfinance", datetime(2026, 1, i + 1, 10, 0, 0), "old")

            # --prune after new backup: 14 old + 1 new = 15 total, keep 14 → 1 deleted
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/backup_database.py",
                    "--reason",
                    "ci-test",
                    "--prune",
                    "--keep-last",
                    "14",
                    "--no-keep-monthly",
                    "--backup-dir",
                    str(backup_dir),
                ],
                capture_output=True,
                text=True,
                cwd=Path(__file__).resolve().parents[1],
                env={
                    **__import__("os").environ,
                    "DATABASE_URL": f"sqlite:///{db_path}",
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            count_after = len(list(backup_dir.iterdir()))
            self.assertEqual(count_after, 14)


if __name__ == "__main__":
    unittest.main()
