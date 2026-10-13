"""encrypt transcripts and LLM output at rest

Revision ID: a1c9f4e27b30
Revises: 3b8f5c2a91de
Create Date: 2026-10-13 21:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a1c9f4e27b30"
down_revision: str | None = "3b8f5c2a91de"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Columns that become opaque encrypted text (plan §16). ``transcripts.full_text``
# was already ``Text``; the JSONB columns hold a JSON array/object and gain a
# single ciphertext string instead.
_COLUMNS: tuple[tuple[str, str], ...] = (
    ("transcripts", "segments"),
    ("agreement_extractions", "raw_output"),
    ("agreement_extractions", "validated_output"),
)


def upgrade() -> None:
    # The ORM now encrypts these values before binding them; the JSONB storage no
    # longer fits, so the columns become text. Existing rows are cast to text and
    # read back as legacy clear text until they are rewritten.
    for table, column in _COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=postgresql.JSONB(astext_type=sa.Text()),
            type_=sa.Text(),
            existing_nullable=column != "raw_output",
            postgresql_using=f"{column}::text",
        )


def downgrade() -> None:
    # Encrypted rows are not valid JSON and cannot be cast back; reset the content
    # to an empty JSON array rather than fail the migration.
    for table, column in _COLUMNS:
        op.execute(f"UPDATE {table} SET {column} = '[]'")
        op.alter_column(
            table,
            column,
            existing_type=sa.Text(),
            type_=postgresql.JSONB(astext_type=sa.Text()),
            existing_nullable=column != "raw_output",
            postgresql_using=f"{column}::jsonb",
        )
