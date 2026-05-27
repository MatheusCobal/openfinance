"""savings_target

Revision ID: 30d7b2b7997f
Revises: d4a9b7c1e2f3
Create Date: 2026-05-26 21:14:11.308658

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '30d7b2b7997f'
down_revision: Union[str, Sequence[str], None] = 'd4a9b7c1e2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'savingstarget',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('monthly_target', sa.Numeric(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'savingstargetoverride',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('year_month', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('monthly_target', sa.Numeric(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('year_month', name='uq_savingstargetoverride_month'),
    )
    op.create_index(
        op.f('ix_savingstargetoverride_year_month'),
        'savingstargetoverride',
        ['year_month'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f('ix_savingstargetoverride_year_month'),
        table_name='savingstargetoverride',
    )
    op.drop_table('savingstargetoverride')
    op.drop_table('savingstarget')
