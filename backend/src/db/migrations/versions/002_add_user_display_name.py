"""Add display_name to users table.

Revision ID: 002_add_user_display_name
Revises: 001_initial_schema
Create Date: 2026-02-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "002_add_user_display_name"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("display_name", sa.String(255), nullable=True))

    # Set default display_name for admin account
    op.execute("UPDATE users SET display_name = 'Jan Kowalski' WHERE role = 'admin' AND display_name IS NULL")


def downgrade() -> None:
    op.drop_column("users", "display_name")
