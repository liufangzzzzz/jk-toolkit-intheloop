"""Persistence owned by Audio Studio.

The tables are separate from the InTheLoop catalogue. A one-time copy keeps
drafts and rules created before the module was separated.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone

from ...database import database

SCHEMA = """
CREATE TABLE IF NOT EXISTS audio_settings (
 key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audio_projects (
 id TEXT PRIMARY KEY, data TEXT NOT NULL,
 revision INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_audio_projects_updated
 ON audio_projects(updated_at DESC);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _table_exists(db: sqlite3.Connection, name: str) -> bool:
    return bool(db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def initialize() -> None:
    with database() as db:
        db.executescript(SCHEMA)
        if _table_exists(db, 'atlas_audio_projects'):
            db.execute(
                'INSERT OR IGNORE INTO audio_projects '
                'SELECT id,data,revision,updated_at FROM atlas_audio_projects'
            )
        if _table_exists(db, 'atlas_settings'):
            db.execute(
                "INSERT OR IGNORE INTO audio_settings "
                "SELECT key,value,updated_at FROM atlas_settings "
                "WHERE key LIKE 'audio-skill-%' OR key='feishu-user-refresh-token'"
            )


def get_setting(key: str, fallback: str = '') -> str:
    initialize()
    with database() as db:
        row = db.execute('SELECT value FROM audio_settings WHERE key=?', (key,)).fetchone()
        return row['value'] if row else fallback


def set_setting(key: str, value: str) -> None:
    initialize()
    with database() as db:
        db.execute(
            'INSERT INTO audio_settings VALUES (?,?,?) '
            'ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at',
            (key, value, now()),
        )


def projects() -> list[dict]:
    initialize()
    with database() as db:
        return [
            json.loads(row['data']) | {
                'id': row['id'],
                'revision': row['revision'],
                'updated_at': row['updated_at'],
            }
            for row in db.execute('SELECT * FROM audio_projects ORDER BY updated_at DESC')
        ]


def save_project(data: dict, record_id: str | None = None) -> dict:
    initialize()
    record_id = record_id or str(uuid.uuid4())
    payload = dict(data)
    expected = int(payload.pop('revision', 0) or 0)
    with database() as db:
        row = db.execute('SELECT revision FROM audio_projects WHERE id=?', (record_id,)).fetchone()
        if row and row['revision'] != expected:
            raise ValueError('工作稿已被更新，请重新打开后再保存')
        revision = row['revision'] + 1 if row else 1
        stamp = now()
        db.execute(
            'INSERT INTO audio_projects VALUES (?,?,?,?) '
            'ON CONFLICT(id) DO UPDATE SET data=excluded.data,'
            'revision=excluded.revision,updated_at=excluded.updated_at',
            (record_id, json.dumps(payload, ensure_ascii=False), revision, stamp),
        )
    return {'id': record_id, 'revision': revision, 'updated_at': stamp}
