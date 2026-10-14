"""store the calendar event id on the task

Revision ID: c4d7e18f5a62
Revises: a1c9f4e27b30
Create Date: 2026-10-14 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4d7e18f5a62"
down_revision: str | None = "a1c9f4e27b30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Until now the event id lived only in ``audit_log``; the task keeps it so the
    # event can be deleted/updated later (plan §12–14, ``DELETE /tasks/{id}/calendar``).
    op.add_column("tasks", sa.Column("calendar_event_id", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "calendar_event_id")
