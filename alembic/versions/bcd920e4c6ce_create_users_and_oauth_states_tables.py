"""create users and oauth_states tables

Revision ID: bcd920e4c6ce
Revises: 
Create Date: 2026-03-22 23:47:54.993130

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bcd920e4c6ce'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('slack_user_id', sa.String(length=64), nullable=False),
        sa.Column('encrypted_access_token', sa.String(length=512), nullable=False),
        sa.Column('encrypted_refresh_token', sa.String(length=512), nullable=True),
        sa.Column('token_expiry', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_users_slack_user_id', 'users', ['slack_user_id'], unique=True)
    op.create_table(
        'oauth_states',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('state', sa.String(length=128), nullable=False),
        sa.Column('slack_user_id', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_oauth_states_state', 'oauth_states', ['state'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_oauth_states_state', table_name='oauth_states')
    op.drop_table('oauth_states')
    op.drop_index('ix_users_slack_user_id', table_name='users')
    op.drop_table('users')
