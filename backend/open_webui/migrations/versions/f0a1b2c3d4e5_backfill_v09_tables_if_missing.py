"""backfill v0.9.x tables if missing on upgraded DBs

Strategy-A recovery per docs/ALEMBIC_MERGE_PLAYBOOK.md (section 7).

History: between 2026-01 and 2026-04 this fork's migration chain was
rewritten several times after upstream merges to resolve divergent
heads. Each rewrite stamped some production DBs at a later revision
than their actual schema. The Stadtbau DB in particular ended up at
head `d8e9f0a1b2c3` while missing six v0.9.x tables: calendar,
calendar_event, calendar_event_attendee, automation, automation_run,
shared_chat. This migration creates them idempotently so both
already-correct DBs and drifted DBs converge on the same schema.

This is a pure forward-only backfill. It does NOT manipulate
`alembic_version` and does NOT replay data migrations from the
original shared_chat migration (c1d2e3f4a5b6) - if a deployment needs
the shared-* chat rows migrated it must run a separate one-off.

Revision ID: f0a1b2c3d4e5
Revises: d8e9f0a1b2c3
Create Date: 2026-04-23 16:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from open_webui.migrations._fork_helpers import (
    _column_exists,
    _table_exists,
    create_table_if_missing,
)


revision: str = "f0a1b2c3d4e5"
down_revision: Union[str, None] = "d8e9f0a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_index_if_missing(index_name: str, table_name: str, columns, unique: bool = False) -> None:
    """Create an index only if it's not already there. Alembic's op.create_index
    itself has no IF NOT EXISTS affordance, so we check pg_indexes /
    sqlite_master manually."""
    conn = op.get_bind()
    if not _table_exists(conn, table_name):
        return
    if conn.dialect.name == "postgresql":
        exists = bool(
            conn.execute(
                sa.text(
                    "SELECT EXISTS(SELECT 1 FROM pg_indexes "
                    "WHERE schemaname='public' AND indexname = :i)"
                ),
                {"i": index_name},
            ).scalar()
        )
    else:
        exists = bool(
            conn.execute(
                sa.text(
                    "SELECT EXISTS(SELECT 1 FROM sqlite_master "
                    "WHERE type='index' AND name = :i)"
                ),
                {"i": index_name},
            ).scalar()
        )
    if exists:
        return
    op.create_index(index_name, table_name, columns, unique=unique)


def upgrade() -> None:
    # --- calendar (56359461a091) ---
    create_table_if_missing(
        "calendar",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("color", sa.Text(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_index_if_missing("ix_calendar_user", "calendar", ["user_id"])

    create_table_if_missing(
        "calendar_event",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("calendar_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("start_at", sa.BigInteger(), nullable=False),
        sa.Column("end_at", sa.BigInteger(), nullable=True),
        sa.Column("all_day", sa.Boolean(), nullable=False),
        sa.Column("rrule", sa.Text(), nullable=True),
        sa.Column("color", sa.Text(), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("is_cancelled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_index_if_missing(
        "ix_calendar_event_calendar", "calendar_event", ["calendar_id", "start_at"]
    )
    _create_index_if_missing(
        "ix_calendar_event_user_date", "calendar_event", ["user_id", "start_at"]
    )

    create_table_if_missing(
        "calendar_event_attendee",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "user_id", name="uq_event_attendee"),
    )
    _create_index_if_missing(
        "ix_calendar_event_attendee_user",
        "calendar_event_attendee",
        ["user_id", "status"],
    )

    # --- automation (d4e5f6a7b8c9) ---
    create_table_if_missing(
        "automation",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, default=True),
        sa.Column("last_run_at", sa.BigInteger(), nullable=True),
        sa.Column("next_run_at", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
    )
    _create_index_if_missing("ix_automation_next_run", "automation", ["next_run_at"])

    create_table_if_missing(
        "automation_run",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("automation_id", sa.Text(), nullable=False),
        sa.Column("chat_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
    )
    _create_index_if_missing(
        "ix_automation_run_automation_id",
        "automation_run",
        ["automation_id"],
    )

    # --- shared_chat (c1d2e3f4a5b6) -- table only, not the data migration ---
    create_table_if_missing(
        "shared_chat",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "chat_id",
            sa.Text(),
            sa.ForeignKey("chat.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("chat", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    # Intentionally no-op. This migration exists only to converge drifted DBs
    # onto their expected schema; reverting it on a DB that already had the
    # tables would destroy data. Use the original per-table downgrade in
    # 56359461a091 / d4e5f6a7b8c9 / c1d2e3f4a5b6 instead.
    pass
