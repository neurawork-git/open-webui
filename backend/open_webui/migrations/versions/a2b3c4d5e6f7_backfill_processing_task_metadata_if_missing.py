"""backfill processing_task.metadata column if missing or mis-named on drifted DBs

Strategy-A recovery per docs/ALEMBIC_MERGE_PLAYBOOK.md (section 7).

Context: The Stolley DB is stamped past `d8e9f0a1b2c3_normalize_processing_task_metadata`
but still reports schema validation failure at startup:

    Column 'metadata' exists in model 'ProcessingTask'
    but not in database table 'processing_task'.

Two drift shapes explain this and this migration handles both idempotently:

1. Column `task_metadata` still present (c7d8e9f0a1b2's rename applied, but
   d8e9f0a1b2c3's rename-back silently skipped on this DB). Rename back to
   `metadata`.
2. Neither `metadata` nor `task_metadata` present (the column was lost during
   one of the 2026-Q1 repair-chain rewrites). Add `metadata` JSON nullable.

Already-correct DBs (column `metadata` already present) are a no-op.

Revision ID: a2b3c4d5e6f7
Revises: f1b2c3d4e5f6
Create Date: 2026-04-24 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from open_webui.migrations._fork_helpers import _column_exists, _table_exists


revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, None] = "f1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    if not _table_exists(conn, "processing_task"):
        # Table itself missing would surface as a different error on startup;
        # out of scope for this backfill. Leave for a separate recovery.
        return

    has_metadata = _column_exists(conn, "processing_task", "metadata")
    has_task_metadata = _column_exists(conn, "processing_task", "task_metadata")

    if has_metadata:
        return

    if has_task_metadata:
        # Quote `metadata` - not reserved, but safer against future SQL parsers.
        op.execute(
            'ALTER TABLE processing_task RENAME COLUMN task_metadata TO "metadata"'
        )
        return

    op.add_column(
        "processing_task",
        sa.Column("metadata", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    # Intentionally no-op - same rationale as f0a1b2c3d4e5 / f1b2c3d4e5f6.
    # Reverting on an already-correct DB would destroy data. Use the original
    # per-column downgrade in a8f52d3c1e7b / d8e9f0a1b2c3 instead.
    pass
