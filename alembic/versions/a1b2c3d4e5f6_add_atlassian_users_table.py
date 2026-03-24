"""add atlassian_users table

Revision ID: a1b2c3d4e5f6
Revises: bcd920e4c6ce
Create Date: 2026-03-23 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'bcd920e4c6ce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'atlassian_users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('slack_user_id', sa.String(length=64), nullable=False),
        sa.Column('encrypted_access_token', sa.String(length=512), nullable=False),
        sa.Column('encrypted_refresh_token', sa.String(length=512), nullable=True),
        sa.Column('token_expiry', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cloud_id', sa.String(length=128), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_atlassian_users_slack_user_id', 'atlassian_users', ['slack_user_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_atlassian_users_slack_user_id', table_name='atlassian_users')
    op.drop_table('atlassian_users')
