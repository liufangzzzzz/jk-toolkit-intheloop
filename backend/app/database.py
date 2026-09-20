from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

_INIT_LOCK = threading.Lock()
_INITIALIZED_PATHS: set[str] = set()


def database_path() -> Path:
    configured = os.environ.get("ITL_DATABASE_PATH", "").strip()
    return Path(configured) if configured else Path.cwd() / ".local-data" / "toolkit.db"


def _open_connection() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def initialize_database() -> None:
    path_key = str(database_path().resolve())
    if path_key in _INITIALIZED_PATHS:
        return
    with _INIT_LOCK:
        if path_key in _INITIALIZED_PATHS:
            return
        statements = [
            """
            CREATE TABLE IF NOT EXISTS publish_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT UNIQUE,
                destination TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_ref TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL,
                external_id TEXT NOT NULL DEFAULT '',
                external_url TEXT NOT NULL DEFAULT '',
                admin_url TEXT NOT NULL DEFAULT '',
                state TEXT NOT NULL,
                warnings_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS import_jobs (
                id TEXT PRIMARY KEY,
                idempotency_key TEXT UNIQUE,
                source_type TEXT NOT NULL,
                status TEXT NOT NULL,
                request_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT NOT NULL DEFAULT '{}',
                error_message TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_publish_records_destination_created ON publish_records(destination, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_import_jobs_status_created ON import_jobs(status, created_at)",
        ]
        with _open_connection() as connection:
            for statement in statements:
                connection.execute(statement)
            publish_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(publish_records)").fetchall()
            }
            if "request_id" not in publish_columns:
                connection.execute("ALTER TABLE publish_records ADD COLUMN request_id TEXT")
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_publish_records_request_id "
                "ON publish_records(request_id) WHERE request_id IS NOT NULL"
            )
            connection.execute("PRAGMA optimize")
            connection.commit()
        _INITIALIZED_PATHS.add(path_key)


@contextmanager
def database() -> Iterator[sqlite3.Connection]:
    initialize_database()
    connection = _open_connection()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
