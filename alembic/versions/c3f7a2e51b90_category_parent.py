"""category_parent

Revision ID: c3f7a2e51b90
Revises: b2c71d9e4f01
Create Date: 2026-05-26 16:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3f7a2e51b90"
down_revision: Union[str, Sequence[str], None] = "b2c71d9e4f01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "category",
        sa.Column("parent_id", sa.Integer(), nullable=True),
    )
    op.create_index(op.f("ix_category_parent_id"), "category", ["parent_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_category_parent_id"), table_name="category")
    op.drop_column("category", "parent_id")
