#!/usr/bin/env python3
"""
Open WebUI SQLite to PostgreSQL Migration Script

Handles:
- Memory-efficient batch processing
- Data type conversions (dates, booleans, JSON)
- Corrupted record handling
- Schema mismatches between old SQLite and new PostgreSQL

Usage:
    python migrate_sqlite_to_postgres.py

Configuration:
    Edit the CONFIG section below or use environment variables.
"""

import sqlite3
import psycopg2
from psycopg2 import sql
from psycopg2.extras import execute_batch
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
import traceback

# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass
class Config:
    # SQLite source
    sqlite_path: str = os.getenv("SQLITE_PATH", "webui.db")

    # PostgreSQL target
    pg_host: str = os.getenv("PG_HOST", "10.10.135.12")
    pg_port: int = int(os.getenv("PG_PORT", "5432"))
    pg_user: str = os.getenv("PG_USER", "dbadmin")
    pg_password: str = os.getenv("PG_PASSWORD", "Blinked6-Defiling")
    pg_database: str = os.getenv("PG_DATABASE", "openwebui")

    # Migration settings
    batch_size: int = int(os.getenv("BATCH_SIZE", "500"))

    # Tables to skip (will be regenerated or managed separately)
    skip_tables: List[str] = None

    def __post_init__(self):
        if self.skip_tables is None:
            self.skip_tables = [
                "document_chunk",      # Vector embeddings - re-index after migration
                "alembic_version",     # Migration tracking - let new DB manage
                "migratehistory",      # Peewee migration tracking
            ]

config = Config()

# ============================================================================
# LOGGING
# ============================================================================

class Logger:
    def __init__(self):
        self.errors: List[Dict] = []
        self.warnings: List[str] = []
        self.stats: Dict[str, Dict] = {}

    def info(self, msg: str):
        print(f"[INFO] {msg}")

    def success(self, msg: str):
        print(f"[OK] {msg}")

    def warning(self, msg: str):
        print(f"[WARN] {msg}")
        self.warnings.append(msg)

    def error(self, msg: str, exception: Exception = None):
        print(f"[ERROR] {msg}")
        error_entry = {"message": msg}
        if exception:
            error_entry["exception"] = str(exception)
            error_entry["traceback"] = traceback.format_exc()
        self.errors.append(error_entry)

    def table_stats(self, table: str, total: int, migrated: int, skipped: int):
        self.stats[table] = {
            "total": total,
            "migrated": migrated,
            "skipped": skipped
        }

    def print_summary(self):
        print("\n" + "=" * 60)
        print("MIGRATION SUMMARY")
        print("=" * 60)

        total_migrated = 0
        total_skipped = 0

        for table, stats in self.stats.items():
            status = "OK" if stats["skipped"] == 0 else "PARTIAL"
            print(f"  {table}: {stats['migrated']}/{stats['total']} rows [{status}]")
            if stats["skipped"] > 0:
                print(f"    -> {stats['skipped']} rows skipped due to errors")
            total_migrated += stats["migrated"]
            total_skipped += stats["skipped"]

        print("-" * 60)
        print(f"  TOTAL: {total_migrated} rows migrated, {total_skipped} rows skipped")

        if self.warnings:
            print(f"\n  Warnings: {len(self.warnings)}")

        if self.errors:
            print(f"\n  Errors: {len(self.errors)}")
            for err in self.errors[:10]:  # Show first 10 errors
                print(f"    - {err['message']}")
            if len(self.errors) > 10:
                print(f"    ... and {len(self.errors) - 10} more errors")

        print("=" * 60)

log = Logger()

# ============================================================================
# DATA TRANSFORMERS
# ============================================================================

def safe_int(value: Any) -> Optional[int]:
    """Safely convert value to integer."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None

def safe_float(value: Any) -> Optional[float]:
    """Safely convert value to float."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None

def safe_bool(value: Any) -> Optional[bool]:
    """Convert SQLite integer boolean to Python bool."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    try:
        return bool(int(value))
    except (ValueError, TypeError):
        return None

def safe_json(value: Any) -> Optional[str]:
    """Ensure value is valid JSON string."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            # Validate it's valid JSON
            json.loads(value)
            return value
        except json.JSONDecodeError:
            # Return as JSON string if not valid JSON
            return json.dumps(value)
    # Convert other types to JSON
    return json.dumps(value)

def safe_timestamp(value: Any) -> Optional[int]:
    """
    Convert various date formats to Unix timestamp (bigint).
    Handles corrupted dates like "1757945880-01-01".
    """
    if value is None:
        return None

    # Already a valid timestamp (integer)
    if isinstance(value, (int, float)):
        # Sanity check: timestamps should be reasonable (1970-2100)
        if 0 <= value <= 4102444800:  # Up to year 2100
            return int(value)
        # Might be milliseconds
        if 0 <= value <= 4102444800000:
            return int(value / 1000)
        return None

    # String value - try to parse
    if isinstance(value, str):
        value = value.strip()

        # Try parsing as integer timestamp
        try:
            ts = int(value)
            if 0 <= ts <= 4102444800:
                return ts
            if 0 <= ts <= 4102444800000:
                return int(ts / 1000)
        except ValueError:
            pass

        # Try parsing as float timestamp
        try:
            ts = float(value)
            if 0 <= ts <= 4102444800:
                return int(ts)
        except ValueError:
            pass

        # Try common date formats
        date_formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d",
        ]

        for fmt in date_formats:
            try:
                dt = datetime.strptime(value, fmt)
                # Sanity check year
                if 1970 <= dt.year <= 2100:
                    return int(dt.timestamp())
            except ValueError:
                continue

        # Corrupted date like "1757945880-01-01" - extract what we can
        if "-" in value:
            parts = value.split("-")
            if len(parts) >= 1:
                try:
                    # Maybe the first part is actually a timestamp
                    ts = int(parts[0])
                    if 0 <= ts <= 4102444800:
                        return ts
                except ValueError:
                    pass

    # Could not convert - return None (will use current time as fallback)
    return None

def transform_row(row: Dict, table_name: str, column_types: Dict[str, str]) -> Dict:
    """Transform a row's values based on target column types."""
    transformed = {}

    for col, value in row.items():
        target_type = column_types.get(col, "text")

        # Handle specific transformations based on target type
        if target_type in ("bigint", "integer", "int4", "int8"):
            # Check if this is a timestamp column
            if col in ("created_at", "updated_at", "timestamp", "last_active_at", "expires_at"):
                transformed[col] = safe_timestamp(value)
                # Use current time if conversion failed
                if transformed[col] is None and value is not None:
                    transformed[col] = int(datetime.now().timestamp())
            else:
                transformed[col] = safe_int(value)

        elif target_type == "boolean":
            transformed[col] = safe_bool(value)

        elif target_type == "json" or target_type == "jsonb":
            transformed[col] = safe_json(value)

        elif target_type in ("double precision", "float8", "real", "float4", "numeric"):
            transformed[col] = safe_float(value)

        else:
            # Keep as-is for text, varchar, etc.
            transformed[col] = value

    return transformed

# ============================================================================
# DATABASE OPERATIONS
# ============================================================================

def get_sqlite_tables(conn: sqlite3.Connection) -> List[str]:
    """Get list of tables in SQLite database."""
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row[0] for row in cursor.fetchall()]
    return [t for t in tables if t not in config.skip_tables and not t.startswith("sqlite_")]

def get_sqlite_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    """Get column names for a SQLite table."""
    cursor = conn.cursor()
    cursor.execute(f'PRAGMA table_info("{table}")')
    return [row[1] for row in cursor.fetchall()]

def get_postgres_columns(conn, table: str) -> Dict[str, str]:
    """Get column names and types for a PostgreSQL table."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
    """, (table,))
    return {row[0]: row[1] for row in cursor.fetchall()}

def get_row_count(conn: sqlite3.Connection, table: str) -> int:
    """Get row count for a SQLite table."""
    cursor = conn.cursor()
    cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
    return cursor.fetchone()[0]

def read_sqlite_batch(conn: sqlite3.Connection, table: str, columns: List[str],
                      offset: int, limit: int) -> List[Dict]:
    """Read a batch of rows from SQLite."""
    cursor = conn.cursor()
    cols = ", ".join(f'"{c}"' for c in columns)
    cursor.execute(f'SELECT {cols} FROM "{table}" LIMIT {limit} OFFSET {offset}')
    rows = cursor.fetchall()
    return [dict(zip(columns, row)) for row in rows]

def truncate_postgres_table(conn, table: str):
    """Truncate a PostgreSQL table."""
    cursor = conn.cursor()
    # Disable triggers temporarily to handle foreign keys
    cursor.execute(f'TRUNCATE TABLE "{table}" CASCADE')
    conn.commit()

def insert_postgres_batch(conn, table: str, rows: List[Dict], columns: List[str]) -> int:
    """Insert a batch of rows into PostgreSQL. Returns number of successful inserts."""
    if not rows:
        return 0

    cursor = conn.cursor()

    # Build parameterized query
    cols = ", ".join(f'"{c}"' for c in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    query = f'INSERT INTO "{table}" ({cols}) VALUES ({placeholders})'

    # Convert rows to tuples
    values = []
    for row in rows:
        values.append(tuple(row.get(c) for c in columns))

    try:
        execute_batch(cursor, query, values, page_size=100)
        conn.commit()
        return len(rows)
    except Exception as e:
        conn.rollback()
        # Try one by one to identify problematic rows
        successful = 0
        for row in rows:
            try:
                cursor.execute(query, tuple(row.get(c) for c in columns))
                conn.commit()
                successful += 1
            except Exception as row_error:
                conn.rollback()
                log.warning(f"Skipped row in {table}: {str(row_error)[:100]}")
        return successful

def add_missing_columns(pg_conn, table: str, sqlite_columns: List[str], pg_columns: Dict[str, str]):
    """Add any columns that exist in SQLite but not in PostgreSQL."""
    missing = set(sqlite_columns) - set(pg_columns.keys())

    if missing:
        cursor = pg_conn.cursor()
        for col in missing:
            log.info(f"Adding missing column {table}.{col}")
            try:
                cursor.execute(f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS "{col}" TEXT')
                pg_conn.commit()
            except Exception as e:
                pg_conn.rollback()
                log.warning(f"Could not add column {table}.{col}: {e}")

# ============================================================================
# KNOWLEDGE FILE MIGRATION (data.file_ids -> knowledge_file table)
# ============================================================================

def migrate_knowledge_file_references(pg_conn) -> Tuple[int, int]:
    """
    Migrate file references from knowledge.data JSON to knowledge_file junction table.

    The old schema stored file_ids in knowledge.data = {"file_ids": [...]}
    The new schema uses a knowledge_file junction table.

    Returns: (migrated_count, skipped_count)
    """
    import uuid
    import time

    log.info("Migrating knowledge file references (data.file_ids -> knowledge_file)...")

    cursor = pg_conn.cursor()

    # Check if knowledge table has a 'data' column
    cursor.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'knowledge' AND column_name = 'data'
    """)
    if not cursor.fetchone():
        log.info("  No 'data' column in knowledge table, skipping")
        return 0, 0

    # Get all knowledge bases with data containing file_ids
    cursor.execute('SELECT id, user_id, name, data FROM knowledge WHERE data IS NOT NULL')
    knowledge_bases = cursor.fetchall()

    if not knowledge_bases:
        log.info("  No knowledge bases with data found")
        return 0, 0

    log.info(f"  Found {len(knowledge_bases)} knowledge bases with data")

    total_migrated = 0
    total_skipped = 0

    for kb_id, user_id, name, data in knowledge_bases:
        if not data:
            continue

        # Parse data JSON
        try:
            if isinstance(data, str):
                data = json.loads(data)
        except json.JSONDecodeError:
            log.warning(f"  Invalid JSON in knowledge {kb_id}")
            continue

        file_ids = data.get('file_ids', [])
        if not file_ids:
            continue

        kb_migrated = 0
        kb_skipped = 0

        for file_id in file_ids:
            # Check if already exists in knowledge_file
            cursor.execute(
                'SELECT 1 FROM knowledge_file WHERE knowledge_id = %s AND file_id = %s',
                (kb_id, file_id)
            )
            if cursor.fetchone():
                kb_skipped += 1
                continue

            # Check if file exists
            cursor.execute('SELECT 1 FROM file WHERE id = %s', (file_id,))
            if not cursor.fetchone():
                kb_skipped += 1
                continue

            # Insert into knowledge_file
            try:
                new_id = str(uuid.uuid4())
                now = int(time.time())
                cursor.execute('''
                    INSERT INTO knowledge_file (id, knowledge_id, file_id, user_id, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                ''', (new_id, kb_id, file_id, user_id, now, now))
                kb_migrated += 1
            except Exception as e:
                pg_conn.rollback()
                kb_skipped += 1
                continue

        pg_conn.commit()

        if kb_migrated > 0:
            log.info(f"    {name}: {kb_migrated} files linked")

        total_migrated += kb_migrated
        total_skipped += kb_skipped

    log.success(f"  Knowledge file references: {total_migrated} migrated, {total_skipped} skipped")
    return total_migrated, total_skipped


# ============================================================================
# MAIN MIGRATION
# ============================================================================

def migrate_table(sqlite_conn: sqlite3.Connection, pg_conn, table: str):
    """Migrate a single table from SQLite to PostgreSQL."""
    log.info(f"Migrating table: {table}")

    # Get columns
    sqlite_columns = get_sqlite_columns(sqlite_conn, table)
    pg_columns = get_postgres_columns(pg_conn, table)

    if not pg_columns:
        log.warning(f"Table {table} does not exist in PostgreSQL, skipping")
        return

    # Add any missing columns to PostgreSQL
    add_missing_columns(pg_conn, table, sqlite_columns, pg_columns)
    pg_columns = get_postgres_columns(pg_conn, table)  # Refresh

    # Use intersection of columns (only migrate columns that exist in both)
    common_columns = [c for c in sqlite_columns if c in pg_columns]

    if not common_columns:
        log.warning(f"No common columns between SQLite and PostgreSQL for {table}, skipping")
        return

    # Get row count
    total_rows = get_row_count(sqlite_conn, table)
    log.info(f"  Total rows: {total_rows}")

    if total_rows == 0:
        log.success(f"  {table}: empty table, nothing to migrate")
        log.table_stats(table, 0, 0, 0)
        return

    # Truncate target table
    log.info(f"  Truncating {table} in PostgreSQL...")
    try:
        truncate_postgres_table(pg_conn, table)
    except Exception as e:
        log.error(f"Failed to truncate {table}: {e}")
        return

    # Migrate in batches
    migrated = 0
    skipped = 0
    offset = 0

    while offset < total_rows:
        # Read batch from SQLite
        rows = read_sqlite_batch(sqlite_conn, table, common_columns, offset, config.batch_size)

        if not rows:
            break

        # Transform rows
        transformed_rows = []
        for row in rows:
            try:
                transformed = transform_row(row, table, pg_columns)
                transformed_rows.append(transformed)
            except Exception as e:
                skipped += 1
                log.warning(f"Transform error in {table}: {e}")

        # Insert batch
        inserted = insert_postgres_batch(pg_conn, table, transformed_rows, common_columns)
        migrated += inserted
        skipped += len(transformed_rows) - inserted

        offset += config.batch_size

        # Progress update every 5000 rows
        if offset % 5000 == 0 or offset >= total_rows:
            pct = min(100, int(offset / total_rows * 100))
            print(f"    Progress: {pct}% ({migrated}/{total_rows} rows)", end="\r")

    print()  # New line after progress
    log.success(f"  {table}: {migrated}/{total_rows} rows migrated")
    log.table_stats(table, total_rows, migrated, skipped)

def run_migration():
    """Main migration function."""
    print("=" * 60)
    print("  Open WebUI SQLite to PostgreSQL Migration")
    print("=" * 60)
    print(f"  Source: {config.sqlite_path}")
    print(f"  Target: postgresql://{config.pg_user}@{config.pg_host}:{config.pg_port}/{config.pg_database}")
    print(f"  Batch size: {config.batch_size}")
    print(f"  Skip tables: {', '.join(config.skip_tables)}")
    print("=" * 60)
    print()

    # Check SQLite file exists
    if not os.path.exists(config.sqlite_path):
        log.error(f"SQLite database not found: {config.sqlite_path}")
        return False

    # Connect to SQLite
    log.info("Connecting to SQLite...")
    try:
        sqlite_conn = sqlite3.connect(config.sqlite_path)
        log.success("Connected to SQLite")
    except Exception as e:
        log.error(f"Failed to connect to SQLite: {e}", e)
        return False

    # Connect to PostgreSQL
    log.info("Connecting to PostgreSQL...")
    try:
        pg_conn = psycopg2.connect(
            host=config.pg_host,
            port=config.pg_port,
            user=config.pg_user,
            password=config.pg_password,
            database=config.pg_database
        )
        log.success("Connected to PostgreSQL")
    except Exception as e:
        log.error(f"Failed to connect to PostgreSQL: {e}", e)
        sqlite_conn.close()
        return False

    # Get tables to migrate
    tables = get_sqlite_tables(sqlite_conn)
    log.info(f"Found {len(tables)} tables to migrate: {', '.join(tables)}")
    print()

    # Migrate each table
    for table in tables:
        try:
            migrate_table(sqlite_conn, pg_conn, table)
        except Exception as e:
            log.error(f"Failed to migrate table {table}: {e}", e)
        print()

    # Close SQLite - no longer needed
    sqlite_conn.close()

    # Post-migration: Migrate knowledge file references
    # (from knowledge.data.file_ids to knowledge_file junction table)
    print()
    try:
        kb_migrated, kb_skipped = migrate_knowledge_file_references(pg_conn)
        log.table_stats("knowledge_file (from data.file_ids)", kb_migrated + kb_skipped, kb_migrated, kb_skipped)
    except Exception as e:
        log.error(f"Failed to migrate knowledge file references: {e}", e)

    # Clean up PostgreSQL connection
    pg_conn.close()

    # Print summary
    log.print_summary()

    # Post-migration notes
    print("\nPOST-MIGRATION STEPS:")
    print("  1. Copy uploads folder to Kubernetes PersistentVolume")
    print("  2. Re-index knowledge bases in Open WebUI to regenerate embeddings")
    print("  3. Verify user logins work correctly")
    print("  4. Test a few chats to ensure data integrity")

    return len(log.errors) == 0

# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    try:
        success = run_migration()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nMigration cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nFATAL ERROR: {e}")
        traceback.print_exc()
        sys.exit(1)
