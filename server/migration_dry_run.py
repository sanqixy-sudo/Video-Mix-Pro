#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


EXPECTED_SCHEMA_COLUMNS = {
    "users": {
        "username": "TEXT",
        "password_hash": "TEXT",
        "is_member": "INTEGER NOT NULL DEFAULT 0",
        "plan": "TEXT",
        "member_expires_at": "TEXT",
        "device_id": "TEXT",
        "device_name": "TEXT",
        "device_bound_at": "TEXT",
        "device_rebind_cooldown_until": "TEXT",
        "is_banned": "INTEGER NOT NULL DEFAULT 0",
        "created_at": "TEXT",
        "updated_at": "TEXT",
    },
    "sessions": {
        "token": "TEXT",
        "user_id": "INTEGER",
        "device_id": "TEXT",
        "created_at": "TEXT",
        "last_seen_at": "TEXT",
    },
    "redeem_codes": {
        "code": "TEXT",
        "plan": "TEXT",
        "custom_days": "INTEGER",
        "batch_id": "TEXT",
        "expires_at": "TEXT",
        "is_disabled": "INTEGER NOT NULL DEFAULT 0",
        "disabled_at": "TEXT",
        "used_by": "INTEGER",
        "used_by_username_snapshot": "TEXT",
        "used_at": "TEXT",
        "created_at": "TEXT",
        "note": "TEXT",
    },
    "app_releases": {
        "channel": "TEXT",
        "latest_version": "TEXT",
        "minimum_version": "TEXT",
        "title": "TEXT",
        "notes": "TEXT",
        "download_url": "TEXT",
        "sha256": "TEXT",
        "is_mandatory": "INTEGER NOT NULL DEFAULT 0",
        "updated_at": "TEXT",
    },
    "app_release_history": {
        "id": "INTEGER",
        "channel": "TEXT",
        "latest_version": "TEXT",
        "minimum_version": "TEXT",
        "title": "TEXT",
        "notes": "TEXT",
        "download_url": "TEXT",
        "sha256": "TEXT",
        "is_mandatory": "INTEGER NOT NULL DEFAULT 0",
        "published_at": "TEXT",
        "published_by": "TEXT",
    },
}

PASSWORD_COLUMNS = ("password_hash", "password", "password_sha256", "passwd", "pwd")


def classify_hash(value: str | None) -> str:
    if not value:
        return "empty"
    if value.startswith("pbkdf2_sha256$"):
        return "pbkdf2_sha256"
    if len(value) == 64 and all(char in "0123456789abcdefABCDEF" for char in value):
        return "sha256_hex"
    if len(value) == 32 and all(char in "0123456789abcdefABCDEF" for char in value):
        return "md5_hex_or_legacy"
    if "$" in value:
        return "unknown_delimited"
    return "unknown_plain_or_custom"


def table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    return [row[0] for row in rows]


def table_columns(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    rows = conn.execute(f"PRAGMA table_info({quote_ident(table)})").fetchall()
    return [
        {"name": row[1], "type": row[2], "notnull": bool(row[3]), "default": row[4], "pk": bool(row[5])}
        for row in rows
    ]


def quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def row_count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {quote_ident(table)}").fetchone()[0])


def password_stats(conn: sqlite3.Connection, table: str, columns: set[str]) -> dict[str, Any]:
    present = [column for column in PASSWORD_COLUMNS if column in columns]
    stats: dict[str, Any] = {"columns": present, "formats": {}, "samples": []}
    if not present:
        return stats
    column = present[0]
    rows = conn.execute(
        f"SELECT {quote_ident(column)} FROM {quote_ident(table)} WHERE {quote_ident(column)} IS NOT NULL LIMIT 50"
    ).fetchall()
    for row in rows:
        value = str(row[0]) if row[0] is not None else ""
        kind = classify_hash(value)
        stats["formats"][kind] = stats["formats"].get(kind, 0) + 1
        if len(stats["samples"]) < 5:
            stats["samples"].append({"format": kind, "prefix": value[:24], "length": len(value)})
    return stats


def inspect_database(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    result: dict[str, Any] = {
        "db_path": str(path),
        "exists": True,
        "tables": {},
        "migration_preview": {"will_backup": False, "missing_tables": [], "missing_columns": {}},
    }
    uri = f"file:{path.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        tables = table_names(conn)
        table_set = set(tables)
        result["table_names"] = tables
        for table in tables:
            columns_info = table_columns(conn, table)
            columns = {column["name"] for column in columns_info}
            result["tables"][table] = {
                "row_count": row_count(conn, table),
                "columns": columns_info,
                "password_hashes": password_stats(conn, table, columns),
            }
        if "schema_migrations" not in table_set:
            result["migration_preview"]["will_backup"] = True
            result["migration_preview"]["missing_tables"].append("schema_migrations")
        for table, expected_columns in EXPECTED_SCHEMA_COLUMNS.items():
            if table not in table_set:
                result["migration_preview"]["will_backup"] = True
                result["migration_preview"]["missing_tables"].append(table)
                result["migration_preview"]["missing_columns"][table] = list(expected_columns)
                continue
            existing = {column["name"] for column in result["tables"][table]["columns"]}
            missing = [column for column in expected_columns if column not in existing]
            if missing:
                result["migration_preview"]["will_backup"] = True
                result["migration_preview"]["missing_columns"][table] = missing
    return result


def print_text(result: dict[str, Any]) -> None:
    print(f"DB: {result['db_path']}")
    print("Tables:")
    for table in result.get("table_names", []):
        info = result["tables"][table]
        column_names = [column["name"] for column in info["columns"]]
        print(f"- {table}: rows={info['row_count']}, columns={', '.join(column_names) or '-'}")
        hash_info = info["password_hashes"]
        if hash_info["columns"]:
            print(f"  password columns: {', '.join(hash_info['columns'])}")
            print(f"  password formats sample: {hash_info['formats']}")
            print(f"  password samples: {hash_info['samples']}")
    preview = result["migration_preview"]
    print("Migration dry-run:")
    print(f"- would create pre-migration backup: {preview['will_backup']}")
    print(f"- missing tables: {preview['missing_tables'] or []}")
    print(f"- missing columns: {preview['missing_columns'] or {}}")
    print("No data was modified; database opened read-only.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only migration dry-run for an old Video Mix SQLite DB.")
    parser.add_argument("db_path", help="Path to app.db or old SQLite database")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text")
    args = parser.parse_args()

    result = inspect_database(Path(args.db_path))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_text(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
