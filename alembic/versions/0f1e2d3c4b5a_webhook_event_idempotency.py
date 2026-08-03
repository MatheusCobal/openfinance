"""enforce Pluggy webhook event idempotency

Revision ID: 0f1e2d3c4b5a
Revises: f4a5b6c7d8e9
Create Date: 2026-07-15 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0f1e2d3c4b5a"
down_revision: Union[str, Sequence[str], None] = "f4a5b6c7d8e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "pluggy_webhook_events"
INDEX = "uq_pluggy_webhook_events_event_id"


def upgrade() -> None:
    # Preserve every historic delivery, but release the duplicated identifiers
    # before creating the unique index. The earliest row keeps the Pluggy id;
    # later rows remain available for diagnostics through their payload.
    op.execute(
        sa.text(
            f"""
            UPDATE {TABLE}
            SET event_id = NULL
            WHERE event_id IS NOT NULL
              AND id NOT IN (
                  SELECT MIN(id)
                  FROM {TABLE}
                  WHERE event_id IS NOT NULL
                  GROUP BY event_id
              )
            """
        )
    )
    op.create_index(
        INDEX,
        TABLE,
        ["event_id"],
        unique=True,
        sqlite_where=sa.text("event_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(INDEX, table_name=TABLE)
