"""backfill v0.9.x columns if missing on upgraded DBs

# FORK: alembic-drift-recovery

Second half of the Strategy-A recovery started by f0a1b2c3d4e5.
Where the first migration caught missing TABLES from upstream merges
that the old repair chain bypassed, this one catches missing COLUMNS
on existing tables. Observed on Stadtbau + Neurawork DBs:

    chat.tasks         (a3dd5bedd151_add_tasks_and_summary_to_chat)
    chat.summary       (a3dd5bedd151_add_tasks_and_summary_to_chat)
    chat.last_read_at  (b7c8d9e0f1a2_add_last_read_at_to_chat)
    note.is_pinned     (e1f2a3b4c5d6_add_is_pinned_to_note)

All additions are idempotent via `add_column_if_missing`. For
chat.last_read_at we also replay the original data backfill
(`UPDATE chat SET last_read_at = updated_at`) but guarded with
`WHERE last_read_at IS NULL` so a re-run cannot clobber rows that
already have the value set.

See docs/ALEMBIC_MERGE_PLAYBOOK.md - Strategy A.

Revision ID: f1b2c3d4e5f6
Revises: f0a1b2c3d4e5
Create Date: 2026-04-24 00:15:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from open_webui.migrations._fork_helpers import (
    _column_exists,
    add_column_if_missing,
)


revision: str = "f1b2c3d4e5f6"
down_revision: Union[str, None] = "f0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # chat.tasks + chat.summary (a3dd5bedd151)
    add_column_if_missing("chat", sa.Column("tasks", sa.JSON(), nullable=True))
    add_column_if_missing("chat", sa.Column("summary", sa.Text(), nullable=True))

    # chat.last_read_at (b7c8d9e0f1a2) - includes the original data backfill,
    # but only for rows that haven't been set yet.
    conn = op.get_bind()
    added_last_read = not _column_exists(conn, "chat", "last_read_at")
    add_column_if_missing(
        "chat", sa.Column("last_read_at", sa.BigInteger(), nullable=True)
    )
    if added_last_read:
        op.execute(
            "UPDATE chat SET last_read_at = updated_at WHERE last_read_at IS NULL"
        )

    # note.is_pinned (e1f2a3b4c5d6)
    add_column_if_missing("note", sa.Column("is_pinned", sa.Boolean(), nullable=True))


def downgrade() -> None:
    # Intentionally no-op. This migration exists only to converge drifted DBs
    # onto their expected schema; reverting it on a DB that already had the
    # columns would destroy data. Use the original per-column downgrade in
    # a3dd5bedd151 / b7c8d9e0f1a2 / e1f2a3b4c5d6 instead.
    pass
