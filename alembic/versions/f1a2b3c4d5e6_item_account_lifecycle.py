"""item_account_lifecycle

Add is_active, last_seen_at, deactivated_at to item and account tables.
Existing rows default to is_active=True so nothing is deactivated on upgrade.

Revision ID: f1a2b3c4d5e6
Revises: e1f5a8c92d10
Create Date: 2026-05-28 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LIFECYCLE_COLUMNS = [
    sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.Column("last_seen_at", sa.DateTime(), nullable=True),
    sa.Column("deactivated_at", sa.DateTime(), nullable=True),
]


def upgrade() -> None:
    with op.batch_alter_table("item") as batch:
        for col in _LIFECYCLE_COLUMNS:
            batch.add_column(col.copy())

    with op.batch_alter_table("account") as batch:
        for col in _LIFECYCLE_COLUMNS:
            batch.add_column(col.copy())


def downgrade() -> None:
    with op.batch_alter_table("account") as batch:
        for col in reversed(_LIFECYCLE_COLUMNS):
            batch.drop_column(col.name)

    with op.batch_alter_table("item") as batch:
        for col in reversed(_LIFECYCLE_COLUMNS):
            batch.drop_column(col.name)
