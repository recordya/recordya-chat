"""Add datasource to chats table.

Revision ID: 003_add_chat_datasource
Revises: 002_add_user_display_name
Create Date: 2026-04-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "003_add_chat_datasource"
down_revision: Union[str, None] = "002_add_user_display_name"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("chats", sa.Column("datasource", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("chats", "datasource")
