"""Safe SQLite restore helpers for OpenFinance."""

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from app.services.database_backup import backup_sqlite_database, sqlite_database_path


class RestoreError(ValueError):
    """Raised when a restore operation fails due to invalid input or validation."""


@dataclass
class RestoreResult:
    source: Path
    destination: Path
    pre_restore_backup: Optional[Path]


def validate_sqlite_database(path: Path) -> None:
    """Verify that path is a readable SQLite file that passes integrity_check.

    Raises RestoreError if the file does not exist, cannot be opened as SQLite,
    or if integrity_check returns any result other than "ok".
    """
    if not path.exists():
        raise RestoreError(f"File not found: {path}")
    try:
        with sqlite3.connect(str(path)) as conn:
            rows = conn.execute("PRAGMA integrity_check").fetchall()
    except Exception as exc:
        raise RestoreError(f"Cannot open {path} as SQLite: {exc}") from exc
    if not rows or rows[0][0] != "ok":
        problems = ", ".join(r[0] for r in rows[:3])
        raise RestoreError(f"Integrity check failed for {path}: {problems}")


def restore_sqlite_database(
    database_url: str,
    backup_path: Union[str, Path],
    backup_dir: Optional[Union[str, Path]] = None,
) -> RestoreResult:
    """Restore a SQLite database from a backup file.

    Steps:
    1. Resolve the destination from database_url (must be file-based SQLite).
    2. Verify backup_path exists and passes integrity_check.
    3. If the destination exists, create a pre-restore backup of it.
    4. Copy backup to a temp file in the same directory as the destination.
    5. Validate the temp copy.
    6. Atomically replace the destination with the temp file.

    Does not delete the backup source.
    Raises RestoreError for any validation failure or unsupported configuration.
    """
    dest_path = sqlite_database_path(database_url)
    if dest_path is None:
        raise RestoreError(
            f"DATABASE_URL does not point to a file-based SQLite database: {database_url!r}"
        )

    backup_path = Path(backup_path).resolve()
    if not backup_path.exists():
        raise RestoreError(f"Backup file not found: {backup_path}")

    validate_sqlite_database(backup_path)

    pre_restore_backup: Optional[Path] = None
    if dest_path.exists():
        pre_restore_backup = backup_sqlite_database(
            database_url, "pre-restore", backup_dir=backup_dir
        )

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_suffix(".restore-tmp.db")
    try:
        with sqlite3.connect(str(backup_path)) as src:
            with sqlite3.connect(str(tmp_path)) as dst:
                src.backup(dst)
        validate_sqlite_database(tmp_path)
        tmp_path.replace(dest_path)
    except RestoreError:
        tmp_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise RestoreError(f"Restore failed during copy: {exc}") from exc

    return RestoreResult(
        source=backup_path,
        destination=dest_path,
        pre_restore_backup=pre_restore_backup,
    )
