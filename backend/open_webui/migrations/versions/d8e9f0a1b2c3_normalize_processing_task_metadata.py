"""normalize processing_task metadata column name

Renames 'task_metadata' back to 'metadata' if an earlier fork migration
renamed it. No-op if the column is already named 'metadata'.

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-04-21 14:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa


revision: str = "d8e9f0a1b2c3"
down_revision: Union[str, None] = "c7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if "processing_task" not in inspector.get_table_names():
        return

    cols = {c["name"] for c in inspector.get_columns("processing_task")}

    if "task_metadata" in cols and "metadata" not in cols:
        # Use raw SQL rename (SQLite 3.25+ supports ALTER COLUMN RENAME)
        op.execute('ALTER TABLE processing_task RENAME COLUMN task_metadata TO "metadata"')


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if "processing_task" not in inspector.get_table_names():
        return

    cols = {c["name"] for c in inspector.get_columns("processing_task")}

    if "metadata" in cols and "task_metadata" not in cols:
        op.execute('ALTER TABLE processing_task RENAME COLUMN "metadata" TO task_metadata')
