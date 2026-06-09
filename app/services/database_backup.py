import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, Union
from urllib.parse import unquote, urlsplit

DEFAULT_BACKUP_DIR = Path("backups")

# Matches the timestamp embedded by backup_sqlite_database: .YYYYMMDD-HHMMSS-ffffff.
_BACKUP_TS_PATTERN = re.compile(r"\.(\d{8}-\d{6}-\d+)\.")


def sqlite_database_path(database_url: str) -> Optional[Path]:
    """Return a file path for SQLite URLs that point to an on-disk database."""
    parsed = urlsplit(database_url)
    if parsed.scheme != "sqlite":
        return None
    if parsed.query and "mode=memory" in parsed.query:
        return None

    raw_path = unquote(database_url.split("?", 1)[0].split("#", 1)[0][len("sqlite://") :])
    if raw_path in {"", "/", ":memory:", "/:memory:"}:
        return None
    if raw_path.startswith("//"):
        path = raw_path[1:]
    elif raw_path.startswith("/"):
        path = raw_path[1:]
    else:
        path = raw_path
    if path in {"", ":memory:"}:
        return None
    return Path(path).expanduser().resolve()


def _sanitize_reason(reason: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", reason.strip()).strip(".-_")
    return sanitized or "backup"


def _backup_suffix(source_path: Path) -> str:
    return source_path.suffix if source_path.suffix in {".db", ".sqlite"} else ".db"


def backup_sqlite_database(
    database_url: str,
    reason: str,
    backup_dir: Optional[Union[str, Path]] = None,
    *,
    timestamp: Optional[datetime] = None,
) -> Optional[Path]:
    """Create a SQLite backup and return its path.

    Non-SQLite URLs, in-memory SQLite URLs, and missing database files are no-ops.
    """
    source_path = sqlite_database_path(database_url)
    if source_path is None or not source_path.exists():
        return None

    target_dir = Path(backup_dir) if backup_dir is not None else DEFAULT_BACKUP_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    captured_at = timestamp or datetime.utcnow()
    filename = (
        f"{source_path.stem}."
        f"{captured_at.strftime('%Y%m%d-%H%M%S-%f')}."
        f"{_sanitize_reason(reason)}"
        f"{_backup_suffix(source_path)}"
    )
    target_path = target_dir / filename

    with sqlite3.connect(str(source_path)) as source:
        with sqlite3.connect(str(target_path)) as target:
            source.backup(target)

    return target_path


def _backup_timestamp(path: Path) -> Optional[datetime]:
    """Extract the embedded timestamp from a backup filename, or None if not parseable."""
    m = _BACKUP_TS_PATTERN.search(path.name)
    if m is None:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d-%H%M%S-%f")
    except ValueError:
        return None


def prune_sqlite_backups(
    backup_dir: Union[str, Path],
    keep_last: int = 14,
    keep_monthly: bool = True,
) -> list[Path]:
    """Remove old backup files, keeping the most recent and optionally one per calendar month.

    Only files whose names contain the app's timestamp pattern are considered.
    Files that do not match are always preserved. Temp files (.restore-tmp.) are skipped.
    Returns a list of deleted paths.
    """
    backup_dir = Path(backup_dir)
    if not backup_dir.exists():
        return []

    parsed: list[tuple[datetime, Path]] = []
    for path in backup_dir.iterdir():
        if not path.is_file():
            continue
        if ".restore-tmp." in path.name:
            continue
        ts = _backup_timestamp(path)
        if ts is not None:
            parsed.append((ts, path))

    if not parsed:
        return []

    parsed.sort(key=lambda x: x[0])

    keep: set[Path] = set()

    for _, path in parsed[-keep_last:]:
        keep.add(path)

    if keep_monthly:
        seen: set[tuple[int, int]] = set()
        for ts, path in parsed:
            key = (ts.year, ts.month)
            if key not in seen:
                seen.add(key)
                keep.add(path)

    deleted: list[Path] = []
    for _, path in parsed:
        if path not in keep:
            try:
                path.unlink()
                deleted.append(path)
            except OSError:
                pass

    return deleted
