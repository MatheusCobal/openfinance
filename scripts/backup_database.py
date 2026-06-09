#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import database_settings  # noqa: E402
from app.services.database_backup import backup_sqlite_database  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a local SQLite backup.")
    parser.add_argument("--reason", default="manual", help="Reason included in backup filename.")
    parser.add_argument("--backup-dir", default=None, help="Directory for generated backups.")
    args = parser.parse_args()

    try:
        backup_path = backup_sqlite_database(
            database_settings.database_url,
            args.reason,
            backup_dir=args.backup_dir,
        )
    except Exception as exc:
        print(f"Backup failed: {exc}", file=sys.stderr)
        return 1

    if backup_path is None:
        print("No SQLite file database found; no backup created.")
        return 0

    print(backup_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
