"""resumable client audio uploads

Revision ID: 3b8f5c2a91de
Revises: 7f3c1a9b2d40
Create Date: 2026-10-13 20:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "3b8f5c2a91de"
down_revision: str | None = "7f3c1a9b2d40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # In-flight chunked upload state (offset, total, stored part keys) per role,
    # so a client whose network dropped can resume without losing audio.
    op.add_column(
        "call_audio",
        sa.Column("pending_uploads", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("call_audio", "pending_uploads")
