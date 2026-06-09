#!/usr/bin/env python3
"""Restore the OpenFinance SQLite database from a backup file.

IMPORTANT: Stop the OpenFinance app before restoring the database.
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import database_settings  # noqa: E402
from app.services.database_restore import RestoreError, restore_sqlite_database  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Restore the OpenFinance SQLite database from a backup file.",
        epilog="IMPORTANT: Stop the OpenFinance app before restoring the database.",
    )
    parser.add_argument(
        "--from",
        dest="source",
        required=True,
        metavar="BACKUP_FILE",
        help="Path to the backup file to restore from.",
    )
    parser.add_argument(
        "--backup-dir",
        default=None,
        metavar="DIR",
        help="Directory to store the pre-restore safety backup (default: backups/).",
    )
    args = parser.parse_args()

    print("IMPORTANT: Stop the OpenFinance app before restoring the database.")
    print()
    print(f"  Source  : {args.source}")
    print(f"  Target  : {database_settings.database_url}")
    print()

    try:
        result = restore_sqlite_database(
            database_settings.database_url,
            args.source,
            backup_dir=args.backup_dir,
        )
    except RestoreError as exc:
        print(f"Restore failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Unexpected error during restore: {exc}", file=sys.stderr)
        return 1

    if result.pre_restore_backup:
        print(f"  Pre-restore backup : {result.pre_restore_backup}")
    else:
        print("  Pre-restore backup : not created (destination did not exist)")
    print(f"  Restored           : {result.source}")
    print(f"  Destination        : {result.destination}")
    print()
    print("Restore complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
