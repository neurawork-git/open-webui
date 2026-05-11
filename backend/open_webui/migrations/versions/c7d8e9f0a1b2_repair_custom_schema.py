"""repair custom schema after merge

# FORK: alembic-drift-recovery

Idempotent repair migration that ensures all custom fork schema exists.
The DB may have been stamped at 665e242be94b without the actual DDL
running (due to a lost migration file during upstream merge).

This migration checks for and creates:
- access_grant table
- skill table
- user.scim column
- processing_task.task_metadata column rename

Revision ID: c7d8e9f0a1b2
Revises: 56359461a091
Create Date: 2026-03-26 09:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa

revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, None] = "56359461a091"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, table_name: str) -> bool:
    """Check table existence via raw SQL to avoid inspector caching issues."""
    dialect = conn.dialect.name
    if dialect == "postgresql":
        result = conn.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = :t)"
            ),
            {"t": table_name},
        )
    else:
        # SQLite fallback
        result = conn.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name = :t)"
            ),
            {"t": table_name},
        )
    return result.scalar()


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    existing_tables = {
        t for t in ["access_grant", "skill", "processing_task"]
        if _table_exists(conn, t)
    }

    # 1. Ensure access_grant table exists
    if "access_grant" not in existing_tables:
        op.create_table(
            "access_grant",
            sa.Column("id", sa.Text(), nullable=False, primary_key=True),
            sa.Column("resource_type", sa.Text(), nullable=False),
            sa.Column("resource_id", sa.Text(), nullable=False),
            sa.Column("principal_type", sa.Text(), nullable=False),
            sa.Column("principal_id", sa.Text(), nullable=False),
            sa.Column("permission", sa.Text(), nullable=False),
            sa.Column("created_at", sa.BigInteger(), nullable=False),
            sa.UniqueConstraint(
                "resource_type",
                "resource_id",
                "principal_type",
                "principal_id",
                "permission",
                name="uq_access_grant_grant",
            ),
        )
        op.create_index(
            "idx_access_grant_resource",
            "access_grant",
            ["resource_type", "resource_id"],
        )
        op.create_index(
            "idx_access_grant_principal",
            "access_grant",
            ["principal_type", "principal_id"],
        )

    # 2. Ensure skill table exists
    if "skill" not in existing_tables:
        op.create_table(
            "skill",
            sa.Column("id", sa.String(), nullable=False, primary_key=True),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("name", sa.Text(), nullable=False, unique=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("meta", sa.JSON(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("updated_at", sa.BigInteger(), nullable=False),
            sa.Column("created_at", sa.BigInteger(), nullable=False),
        )
        op.create_index("idx_skill_user_id", "skill", ["user_id"])
        op.create_index("idx_skill_updated_at", "skill", ["updated_at"])

    # 3. Ensure user.scim column exists
    user_columns = {c["name"] for c in inspector.get_columns("user")}
    if "scim" not in user_columns:
        op.add_column("user", sa.Column("scim", sa.JSON(), nullable=True))

    # 4. Ensure processing_task.task_metadata column exists (rename from metadata)
    if "processing_task" in existing_tables:
        pt_columns = {c["name"] for c in inspector.get_columns("processing_task")}
        if "metadata" in pt_columns and "task_metadata" not in pt_columns:
            op.alter_column(
                "processing_task", "metadata", new_column_name="task_metadata"
            )


def downgrade() -> None:
    # This is a repair migration - downgrade is a no-op since the original
    # migrations handle their own downgrade logic
    pass
