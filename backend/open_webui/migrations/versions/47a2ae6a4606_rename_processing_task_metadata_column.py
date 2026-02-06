"""rename_processing_task_metadata_column

Rename 'metadata' column to 'task_metadata' in processing_task table.

The original migration used 'metadata' which is a reserved word in SQLAlchemy.
This migration renames it to 'task_metadata' to avoid conflicts.

This migration is IDEMPOTENT - it checks the current state before making changes:
- If 'metadata' exists and 'task_metadata' doesn't: renames the column
- If 'task_metadata' already exists: does nothing (already migrated)
- If neither exists: the table structure is unexpected, raises an error

Revision ID: 47a2ae6a4606
Revises: a8f52d3c1e7b
Create Date: 2026-02-06 15:01:58.773044

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa
import open_webui.internal.db


# revision identifiers, used by Alembic.
revision: str = '47a2ae6a4606'
down_revision: Union[str, None] = 'a8f52d3c1e7b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rename 'metadata' to 'task_metadata' if needed."""
    conn = op.get_bind()
    inspector = inspect(conn)

    # Check if table exists
    tables = inspector.get_table_names()
    if 'processing_task' not in tables:
        # Table doesn't exist yet - will be created by previous migration
        # Nothing to rename
        return

    # Get current columns
    columns = {c['name'] for c in inspector.get_columns('processing_task')}

    has_metadata = 'metadata' in columns
    has_task_metadata = 'task_metadata' in columns

    if has_task_metadata:
        # Already renamed (either manually or by a previous run)
        # Nothing to do
        return

    if has_metadata:
        # Need to rename: metadata -> task_metadata
        # SQLite doesn't support ALTER COLUMN RENAME, so we need to recreate
        dialect = conn.dialect.name

        if dialect == 'sqlite':
            # SQLite: Use batch mode to recreate table with new column name
            with op.batch_alter_table('processing_task') as batch_op:
                batch_op.alter_column('metadata', new_column_name='task_metadata')
        else:
            # PostgreSQL, MySQL, etc.: Direct rename supported
            op.alter_column('processing_task', 'metadata', new_column_name='task_metadata')
        return

    # Neither column exists - unexpected state
    raise RuntimeError(
        "processing_task table exists but has neither 'metadata' nor 'task_metadata' column. "
        "This indicates a corrupted or manually modified schema. "
        "Please check the table structure and add the missing column manually."
    )


def downgrade() -> None:
    """Rename 'task_metadata' back to 'metadata' if needed."""
    conn = op.get_bind()
    inspector = inspect(conn)

    tables = inspector.get_table_names()
    if 'processing_task' not in tables:
        return

    columns = {c['name'] for c in inspector.get_columns('processing_task')}

    has_metadata = 'metadata' in columns
    has_task_metadata = 'task_metadata' in columns

    if has_metadata:
        # Already has old name
        return

    if has_task_metadata:
        dialect = conn.dialect.name

        if dialect == 'sqlite':
            with op.batch_alter_table('processing_task') as batch_op:
                batch_op.alter_column('task_metadata', new_column_name='metadata')
        else:
            op.alter_column('processing_task', 'task_metadata', new_column_name='metadata')
