"""fixed_cost_default_categories

Revision ID: b2c71d9e4f01
Revises: 9a8f18c4e5d2
Create Date: 2026-05-26 13:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b2c71d9e4f01"
down_revision: Union[str, Sequence[str], None] = "9a8f18c4e5d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "fixedcostcategory",
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        op.f("ix_fixedcostcategory_is_default"),
        "fixedcostcategory",
        ["is_default"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_fixedcostcategory_is_default"),
        table_name="fixedcostcategory",
    )
    op.drop_column("fixedcostcategory", "is_default")
