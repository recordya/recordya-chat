"""Add langfuse_trace_id to chat messages.

Revision ID: 008_message_langfuse_trace_id
Revises: 007_message_feedback
Create Date: 2026-06-25

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "008_message_langfuse_trace_id"
down_revision: str | None = "007_message_feedback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column("langfuse_trace_id", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_messages", "langfuse_trace_id")
