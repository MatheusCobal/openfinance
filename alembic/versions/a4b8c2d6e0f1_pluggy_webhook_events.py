"""pluggy_webhook_events

Revision ID: a4b8c2d6e0f1
Revises: f7c1a2b3d4e5
Create Date: 2026-06-15 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a4b8c2d6e0f1"
down_revision: Union[str, Sequence[str], None] = "f7c1a2b3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pluggy_webhook_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event", sa.String(), nullable=False),
        sa.Column("event_id", sa.String(), nullable=True),
        sa.Column("item_id", sa.String(), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("payload_json", sa.String(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("sync_started_at", sa.DateTime(), nullable=True),
        sa.Column("sync_finished_at", sa.DateTime(), nullable=True),
        sa.Column("sync_status", sa.String(), nullable=True),
        sa.Column("sync_error", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_pluggy_webhook_events_action"),
        "pluggy_webhook_events",
        ["action"],
        unique=False,
    )
    op.create_index(
        op.f("ix_pluggy_webhook_events_event"),
        "pluggy_webhook_events",
        ["event"],
        unique=False,
    )
    op.create_index(
        op.f("ix_pluggy_webhook_events_event_id"),
        "pluggy_webhook_events",
        ["event_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_pluggy_webhook_events_item_id"),
        "pluggy_webhook_events",
        ["item_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_pluggy_webhook_events_received_at"),
        "pluggy_webhook_events",
        ["received_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_pluggy_webhook_events_sync_status"),
        "pluggy_webhook_events",
        ["sync_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_pluggy_webhook_events_sync_status"), table_name="pluggy_webhook_events")
    op.drop_index(op.f("ix_pluggy_webhook_events_received_at"), table_name="pluggy_webhook_events")
    op.drop_index(op.f("ix_pluggy_webhook_events_item_id"), table_name="pluggy_webhook_events")
    op.drop_index(op.f("ix_pluggy_webhook_events_event_id"), table_name="pluggy_webhook_events")
    op.drop_index(op.f("ix_pluggy_webhook_events_event"), table_name="pluggy_webhook_events")
    op.drop_index(op.f("ix_pluggy_webhook_events_action"), table_name="pluggy_webhook_events")
    op.drop_table("pluggy_webhook_events")
