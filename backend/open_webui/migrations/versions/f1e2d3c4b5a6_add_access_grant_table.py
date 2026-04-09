"""Add access_grant table

Revision ID: f1e2d3c4b5a6
Revises: 8452d01d26d7
Create Date: 2026-02-05 10:00:00.000000

Migrates from JSON access_control columns to normalized access_grant table.
Access control semantics:
- NULL: Public access (all users can read) -> insert user:* for read
- {}: Private/owner-only (no grants) -> insert nothing
- {read: {...}, write: {...}}: Custom permissions -> insert specific grants
"""

from typing import Sequence, Union
import json
import logging
import time
import uuid

from alembic import op
import sqlalchemy as sa

log = logging.getLogger(__name__)

revision: str = 'f1e2d3c4b5a6'
down_revision: Union[str, None] = '8452d01d26d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# INSERT with ON CONFLICT DO NOTHING — idempotent, no silent failures
_UPSERT_SQL = sa.text("""
    INSERT INTO access_grant (id, resource_type, resource_id, principal_type, principal_id, permission, created_at)
    VALUES (:id, :resource_type, :resource_id, :principal_type, :principal_id, :permission, :created_at)
    ON CONFLICT ON CONSTRAINT uq_access_grant_grant DO NOTHING
""")

# SQLite equivalent (no ON CONFLICT on named constraints)
_UPSERT_SQL_SQLITE = sa.text("""
    INSERT OR IGNORE INTO access_grant (id, resource_type, resource_id, principal_type, principal_id, permission, created_at)
    VALUES (:id, :resource_type, :resource_id, :principal_type, :principal_id, :permission, :created_at)
""")


def _table_exists(conn, table_name: str) -> bool:
    """Check table existence via raw SQL — reliable across dialects."""
    dialect = conn.dialect.name
    if dialect == 'postgresql':
        result = conn.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = :t)"
            ),
            {'t': table_name},
        )
    else:
        result = conn.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name = :t)"
            ),
            {'t': table_name},
        )
    return result.scalar()


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    """Check column existence via raw SQL."""
    dialect = conn.dialect.name
    if dialect == 'postgresql':
        result = conn.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :t AND column_name = :c)"
            ),
            {'t': table_name, 'c': column_name},
        )
    else:
        # SQLite: parse table_info
        cols = conn.execute(sa.text(f'PRAGMA table_info("{table_name}")')).fetchall()
        return any(c[1] == column_name for c in cols)
    return result.scalar()


def _insert_grant(conn, upsert_sql, resource_type, resource_id, principal_type, principal_id, permission, now):
    """Insert a single grant, returns True if inserted."""
    conn.execute(
        upsert_sql,
        {
            'id': str(uuid.uuid4()),
            'resource_type': resource_type,
            'resource_id': resource_id,
            'principal_type': principal_type,
            'principal_id': principal_id,
            'permission': permission,
            'created_at': now,
        },
    )


def upgrade() -> None:
    conn = op.get_bind()
    is_pg = conn.dialect.name == 'postgresql'

    # 1. Create access_grant table if it doesn't exist
    if not _table_exists(conn, 'access_grant'):
        op.create_table(
            'access_grant',
            sa.Column('id', sa.Text(), nullable=False, primary_key=True),
            sa.Column('resource_type', sa.Text(), nullable=False),
            sa.Column('resource_id', sa.Text(), nullable=False),
            sa.Column('principal_type', sa.Text(), nullable=False),
            sa.Column('principal_id', sa.Text(), nullable=False),
            sa.Column('permission', sa.Text(), nullable=False),
            sa.Column('created_at', sa.BigInteger(), nullable=False),
            sa.UniqueConstraint(
                'resource_type',
                'resource_id',
                'principal_type',
                'principal_id',
                'permission',
                name='uq_access_grant_grant',
            ),
        )
        op.create_index(
            'idx_access_grant_resource',
            'access_grant',
            ['resource_type', 'resource_id'],
        )
        op.create_index(
            'idx_access_grant_principal',
            'access_grant',
            ['principal_type', 'principal_id'],
        )

    # 2. Backfill from access_control JSON columns (idempotent — always runs)
    upsert_sql = _UPSERT_SQL if is_pg else _UPSERT_SQL_SQLITE

    resource_tables = [
        ('knowledge', 'knowledge'),
        ('prompt', 'prompt'),
        ('tool', 'tool'),
        ('model', 'model'),
        ('note', 'note'),
        ('channel', 'channel'),
        ('file', 'file'),
    ]

    now = int(time.time())
    total_inserted = 0

    for table_name, resource_type in resource_tables:
        if not _table_exists(conn, table_name):
            continue
        if not _column_exists(conn, table_name, 'access_control'):
            log.info(f'  {table_name}: access_control column already dropped, skipping backfill')
            continue

        try:
            result = conn.execute(sa.text(f'SELECT id, access_control FROM "{table_name}"'))
            rows = result.fetchall()
        except Exception as e:
            log.warning(f'  {table_name}: failed to read access_control: {e}')
            continue

        table_inserted = 0
        for row in rows:
            resource_id = row[0]
            ac_raw = row[1]

            # Parse access_control value
            is_null = (
                ac_raw is None
                or ac_raw == 'null'
                or (isinstance(ac_raw, str) and ac_raw.strip().lower() == 'null')
            )

            if is_null:
                # Files: NULL = private (owner-only), no grant needed
                # Other resources: NULL = public (user:* read)
                if resource_type != 'file':
                    _insert_grant(conn, upsert_sql, resource_type, resource_id, 'user', '*', 'read', now)
                    table_inserted += 1
                continue

            # Parse JSON
            ac = ac_raw
            if isinstance(ac, str):
                try:
                    ac = json.loads(ac)
                except (json.JSONDecodeError, ValueError) as e:
                    log.warning(f'  {table_name}/{resource_id}: invalid JSON: {e}')
                    continue

            if not ac or not isinstance(ac, dict):
                continue

            # Extract and insert grants for each permission level
            for permission in ['read', 'write']:
                perm_data = ac.get(permission, {})
                if not perm_data or not isinstance(perm_data, dict):
                    continue

                for group_id in perm_data.get('group_ids', []):
                    _insert_grant(conn, upsert_sql, resource_type, resource_id, 'group', group_id, permission, now)
                    table_inserted += 1

                for user_id in perm_data.get('user_ids', []):
                    _insert_grant(conn, upsert_sql, resource_type, resource_id, 'user', user_id, permission, now)
                    table_inserted += 1

        total_inserted += table_inserted
        log.info(f'  {table_name}: processed {len(rows)} rows, {table_inserted} grants upserted')

    log.info(f'access_grant backfill complete: {total_inserted} total grants upserted')

    # 3. Drop access_control columns (only if backfill succeeded)
    for table_name, _ in resource_tables:
        if not _table_exists(conn, table_name):
            continue
        if not _column_exists(conn, table_name, 'access_control'):
            continue
        try:
            with op.batch_alter_table(table_name) as batch:
                batch.drop_column('access_control')
            log.info(f'  {table_name}: dropped access_control column')
        except Exception as e:
            log.warning(f'  {table_name}: could not drop access_control column: {e}')


def downgrade() -> None:
    import json

    conn = op.get_bind()

    # Resource tables mapping: (table_name, resource_type)
    resource_tables = [
        ('knowledge', 'knowledge'),
        ('prompt', 'prompt'),
        ('tool', 'tool'),
        ('model', 'model'),
        ('note', 'note'),
        ('channel', 'channel'),
        ('file', 'file'),
    ]

    # Step 1: Re-add access_control columns to resource tables
    for table_name, _ in resource_tables:
        try:
            with op.batch_alter_table(table_name) as batch:
                batch.add_column(sa.Column('access_control', sa.JSON(), nullable=True))
        except Exception:
            pass

    # Step 2: Query access_grant table and reconstruct JSON for each resource
    for table_name, resource_type in resource_tables:
        try:
            # Get all grants for this resource type
            result = conn.execute(
                sa.text("""
                    SELECT resource_id, principal_type, principal_id, permission
                    FROM access_grant
                    WHERE resource_type = :resource_type
                """),
                {'resource_type': resource_type},
            )
            rows = result.fetchall()
        except Exception:
            continue

        # Group by resource_id and reconstruct JSON structure
        resource_grants = {}
        for row in rows:
            resource_id = row[0]
            principal_type = row[1]
            principal_id = row[2]
            permission = row[3]

            if resource_id not in resource_grants:
                resource_grants[resource_id] = {
                    'is_public': False,
                    'read': {'group_ids': [], 'user_ids': []},
                    'write': {'group_ids': [], 'user_ids': []},
                }

            # Handle public access (user:* for read)
            if principal_type == 'user' and principal_id == '*' and permission == 'read':
                resource_grants[resource_id]['is_public'] = True
                continue

            # Add to appropriate list
            if permission in ['read', 'write']:
                if principal_type == 'group':
                    if principal_id not in resource_grants[resource_id][permission]['group_ids']:
                        resource_grants[resource_id][permission]['group_ids'].append(principal_id)
                elif principal_type == 'user':
                    if principal_id not in resource_grants[resource_id][permission]['user_ids']:
                        resource_grants[resource_id][permission]['user_ids'].append(principal_id)

        # Step 3: Update each resource with reconstructed JSON
        for resource_id, grants in resource_grants.items():
            if grants['is_public']:
                # Public = NULL
                access_control_value = None
            elif (
                not grants['read']['group_ids']
                and not grants['read']['user_ids']
                and not grants['write']['group_ids']
                and not grants['write']['user_ids']
            ):
                # No grants = should not happen (would mean no entries), default to {}
                access_control_value = json.dumps({})
            else:
                # Custom permissions
                access_control_value = json.dumps(
                    {
                        'read': grants['read'],
                        'write': grants['write'],
                    }
                )

            try:
                conn.execute(
                    sa.text(f'UPDATE "{table_name}" SET access_control = :access_control WHERE id = :id'),
                    {'access_control': access_control_value, 'id': resource_id},
                )
            except Exception:
                pass

        # Step 4: Set all resources WITHOUT entries to private
        # For files: NULL means private (owner-only), so leave as NULL
        # For other resources: {} means private, so update to {}
        if resource_type != 'file':
            try:
                conn.execute(
                    sa.text(f"""
                        UPDATE "{table_name}" 
                        SET access_control = :private_value
                        WHERE id NOT IN (
                            SELECT DISTINCT resource_id FROM access_grant WHERE resource_type = :resource_type
                        )
                        AND access_control IS NULL
                    """),
                    {'private_value': json.dumps({}), 'resource_type': resource_type},
                )
            except Exception:
                pass
        # For files, NULL stays NULL - no action needed

    # Step 5: Drop the access_grant table
    op.drop_index('idx_access_grant_principal', table_name='access_grant')
    op.drop_index('idx_access_grant_resource', table_name='access_grant')
    op.drop_table('access_grant')
