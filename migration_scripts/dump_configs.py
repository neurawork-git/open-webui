#!/usr/bin/env python3
"""
Dump all configs from the Open WebUI SQLite database.

Usage:
    python dump_configs.py [--db PATH] [--format json|table]

Options:
    --db PATH       Path to the SQLite database (default: ../backend/data/webui.db)
    --format        Output format: 'json' (default) or 'table'
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from datetime import datetime


def get_db_path(custom_path: str = None) -> Path:
    """Get the database path."""
    if custom_path:
        return Path(custom_path)

    # Default: webui.db in the same folder as this script
    script_dir = Path(__file__).parent
    return script_dir / "webui.db"


def dump_configs(db_path: Path, output_format: str = "json") -> None:
    """Dump all configs from the database."""

    if not db_path.exists():
        print(f"Error: Database not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get all configs
    cursor.execute("SELECT id, data, version, created_at, updated_at FROM config ORDER BY id")
    rows = cursor.fetchall()

    if not rows:
        print("No configs found in the database.")
        conn.close()
        return

    if output_format == "json":
        output_json(rows)
    else:
        output_table(rows)

    conn.close()


def output_json(rows) -> None:
    """Output configs as JSON."""
    configs = []
    for row in rows:
        config = {
            "id": row["id"],
            "version": row["version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "data": json.loads(row["data"]) if row["data"] else None
        }
        configs.append(config)

    print(json.dumps(configs, indent=2, default=str))


def output_table(rows) -> None:
    """Output configs as a formatted table."""
    print("=" * 100)
    print(f"{'ID':<5} {'Version':<10} {'Created At':<25} {'Updated At':<25}")
    print("=" * 100)

    for row in rows:
        print(f"{row['id']:<5} {row['version']:<10} {row['created_at'] or 'N/A':<25} {row['updated_at'] or 'N/A':<25}")

        # Parse and print config data
        if row["data"]:
            try:
                data = json.loads(row["data"])
                print("-" * 100)
                print("Config Data:")
                print("-" * 100)

                # Print each config key-value pair
                for key, value in sorted(data.items()):
                    value_str = json.dumps(value, default=str) if not isinstance(value, str) else value
                    # Truncate long values
                    if len(value_str) > 80:
                        value_str = value_str[:77] + "..."
                    print(f"  {key}: {value_str}")
            except json.JSONDecodeError:
                print(f"  [Invalid JSON data]")

        print("=" * 100)


def main():
    parser = argparse.ArgumentParser(
        description="Dump all configs from the Open WebUI SQLite database"
    )
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Path to the SQLite database (default: ../backend/data/webui.db)"
    )
    parser.add_argument(
        "--format",
        type=str,
        choices=["json", "table"],
        default="json",
        help="Output format: 'json' (default) or 'table'"
    )

    args = parser.parse_args()

    db_path = get_db_path(args.db)
    print(f"Reading configs from: {db_path}", file=sys.stderr)

    dump_configs(db_path, args.format)


if __name__ == "__main__":
    main()
