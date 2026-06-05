"""
Idempotency guards for fork-local Alembic migrations.

DO NOT USE in upstream migrations. Upstream migrations must stay
byte-identical to the upstream repository so that our Alembic chain
remains rebase-friendly.

Reference: docs/ALEMBIC_MERGE_PLAYBOOK.md, section 9.
"""

from alembic import op
import sqlalchemy as sa


def _dialect(conn) -> str:
    return conn.dialect.name


def _table_exists(conn, table_name: str) -> bool:
    if _dialect(conn) == "postgresql":
        return bool(
            conn.execute(
                sa.text(
                    "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name = :t)"
                ),
                {"t": table_name},
            ).scalar()
        )
    # SQLite fallback (dev only)
    return bool(
        conn.execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name = :t)"
            ),
            {"t": table_name},
        ).scalar()
    )


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    if _dialect(conn) == "postgresql":
        return bool(
            conn.execute(
                sa.text(
                    "SELECT EXISTS(SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema = 'public' "
                    "AND table_name = :t AND column_name = :c)"
                ),
                {"t": table_name, "c": column_name},
            ).scalar()
        )
    rows = conn.execute(sa.text(f"PRAGMA table_info({table_name})")).fetchall()
    return any(r[1] == column_name for r in rows)


def create_table_if_missing(table_name: str, *columns, **kwargs) -> None:
    """Like op.create_table, but a no-op if the table already exists."""
    conn = op.get_bind()
    if _table_exists(conn, table_name):
        return
    op.create_table(table_name, *columns, **kwargs)


def add_column_if_missing(table_name: str, column: sa.Column) -> None:
    """Like op.add_column, but a no-op if the column already exists on the table."""
    conn = op.get_bind()
    if not _table_exists(conn, table_name):
        return
    if _column_exists(conn, table_name, column.name):
        return
    op.add_column(table_name, column)


def drop_table_if_exists(table_name: str) -> None:
    conn = op.get_bind()
    if not _table_exists(conn, table_name):
        return
    op.drop_table(table_name)


def drop_column_if_exists(table_name: str, column_name: str) -> None:
    conn = op.get_bind()
    if not _table_exists(conn, table_name):
        return
    if not _column_exists(conn, table_name, column_name):
        return
    op.drop_column(table_name, column_name)


__all__ = [
    "create_table_if_missing",
    "add_column_if_missing",
    "drop_table_if_exists",
    "drop_column_if_exists",
]
