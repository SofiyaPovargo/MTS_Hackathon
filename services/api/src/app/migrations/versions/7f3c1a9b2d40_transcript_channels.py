"""transcript channels and roles

Revision ID: 7f3c1a9b2d40
Revises: ee8b295d7610
Create Date: 2026-10-13 18:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = '7f3c1a9b2d40'
down_revision: str | None = 'ee8b295d7610'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Per-leg objects for channel-separated (VoIP) recordings.
    op.add_column(
        'call_audio',
        sa.Column('channel_urls', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    # Segmented transcript + how speaker roles were obtained (audit).
    op.add_column(
        'transcripts',
        sa.Column('segments', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        'transcripts',
        sa.Column(
            'role_source',
            sa.String(length=16),
            server_default='unknown',
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column('transcripts', 'role_source')
    op.drop_column('transcripts', 'segments')
    op.drop_column('call_audio', 'channel_urls')
