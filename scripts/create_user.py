"""Create or update an OpenFinance login user.

There is no public signup: users are provisioned with this script. It hashes the
password with Argon2id and writes a row to the ``users`` table. Running it again
for the same email resets that user's password.

Usage:
    python scripts/create_user.py --email you@example.com
    python scripts/create_user.py --email you@example.com --password 's3cret'

In production, run it inside the app container so it targets the same database:
    docker compose -f docker-compose.prod.yml exec openfinance \\
        python scripts/create_user.py --email you@example.com

The password is prompted interactively when --password is omitted, which avoids
leaving it in shell history.
"""

import argparse
import getpass
import sys

from sqlmodel import Session, select

from app.auth.passwords import hash_password
from app.database import engine, init_db
from app.models import User


def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create or update an OpenFinance user.")
    parser.add_argument("--email", required=True, help="User email (used to log in).")
    parser.add_argument(
        "--password",
        help="Password. If omitted, you will be prompted (recommended).",
    )
    return parser.parse_args(argv)


def _resolve_password(provided: str) -> str:
    if provided:
        return provided
    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Passwords do not match.", file=sys.stderr)
        raise SystemExit(1)
    return password


def main(argv=None) -> int:
    args = _parse_args(argv)
    email = args.email.strip().lower()
    password = _resolve_password(args.password)
    if not email or not password:
        print("Email and password are required.", file=sys.stderr)
        return 1

    # Ensure the schema is migrated before writing (safe and idempotent: a no-op
    # when the app has already started and applied migrations).
    init_db()

    with Session(engine) as db:
        user = db.exec(select(User).where(User.email == email)).first()
        if user is None:
            user = User(email=email, password_hash=hash_password(password))
            db.add(user)
            action = "created"
        else:
            user.password_hash = hash_password(password)
            user.is_active = True
            db.add(user)
            action = "updated (password reset)"
        db.commit()
        db.refresh(user)

    print(f"User {email!r} {action} (id={user.id}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
