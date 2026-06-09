#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import database_settings  # noqa: E402
from app.services.database_backup import (  # noqa: E402
    DEFAULT_BACKUP_DIR,
    backup_sqlite_database,
    prune_sqlite_backups,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a local SQLite backup.")
    parser.add_argument("--reason", default="manual", help="Reason included in backup filename.")
    parser.add_argument(
        "--backup-dir",
        default=None,
        metavar="DIR",
        help="Directory for generated backups (default: backups/).",
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="Prune old backups after creating the new backup.",
    )
    parser.add_argument(
        "--prune-only",
        action="store_true",
        help="Prune old backups without creating a new backup.",
    )
    parser.add_argument(
        "--keep-last",
        type=int,
        default=14,
        metavar="N",
        help="Number of most recent backups to keep when pruning (default: 14).",
    )
    parser.add_argument(
        "--keep-monthly",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Keep the first backup of each calendar month (default: on).",
    )
    args = parser.parse_args()

    backup_dir = Path(args.backup_dir) if args.backup_dir else DEFAULT_BACKUP_DIR

    if args.prune_only:
        deleted = prune_sqlite_backups(
            backup_dir,
            keep_last=args.keep_last,
            keep_monthly=args.keep_monthly,
        )
        if deleted:
            for p in deleted:
                print(f"removed: {p}")
            print(f"Pruned {len(deleted)} backup(s).")
        else:
            print("Nothing to prune.")
        return 0

    try:
        backup_path = backup_sqlite_database(
            database_settings.database_url,
            args.reason,
            backup_dir=backup_dir,
        )
    except Exception as exc:
        print(f"Backup failed: {exc}", file=sys.stderr)
        return 1

    if backup_path is None:
        print("No SQLite file database found; no backup created.")
    else:
        print(backup_path)

    if args.prune:
        deleted = prune_sqlite_backups(
            backup_dir,
            keep_last=args.keep_last,
            keep_monthly=args.keep_monthly,
        )
        if deleted:
            for p in deleted:
                print(f"removed: {p}")
            print(f"Pruned {len(deleted)} backup(s).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
