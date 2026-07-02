"""Normalize message feedback saved_time values.

Revision ID: 009_normalize_feedback_time
Revises: 008_message_langfuse_trace_id
Create Date: 2026-06-26

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "009_normalize_feedback_time"
down_revision: str | None = "008_message_langfuse_trace_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE message_feedback
        SET saved_time = CASE saved_time
            WHEN 'do 15 min' THEN 'up_to_15_min'
            WHEN 'do 30 min' THEN 'up_to_30_min'
            WHEN 'do 1h' THEN 'up_to_1h'
            WHEN 'do 2h' THEN 'up_to_2h'
            WHEN 'do 3h' THEN 'up_to_3h'
            WHEN 'powyżej 3h' THEN 'over_3h'
            ELSE saved_time
        END
        WHERE saved_time IN ('do 15 min', 'do 30 min', 'do 1h', 'do 2h', 'do 3h', 'powyżej 3h')
        """
    )



def downgrade() -> None:
    op.execute(
        """
        UPDATE message_feedback
        SET saved_time = CASE saved_time
            WHEN 'up_to_15_min' THEN 'do 15 min'
            WHEN 'up_to_30_min' THEN 'do 30 min'
            WHEN 'up_to_1h' THEN 'do 1h'
            WHEN 'up_to_2h' THEN 'do 2h'
            WHEN 'up_to_3h' THEN 'do 3h'
            WHEN 'over_3h' THEN 'powyżej 3h'
            ELSE saved_time
        END
        WHERE saved_time IN (
            'up_to_15_min',
            'up_to_30_min',
            'up_to_1h',
            'up_to_2h',
            'up_to_3h',
            'over_3h'
        )
        """
    )
