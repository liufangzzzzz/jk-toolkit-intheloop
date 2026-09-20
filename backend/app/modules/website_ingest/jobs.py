from __future__ import annotations

import json
import uuid
from typing import Any

from ...database import database


def get_job_by_key(idempotency_key: str) -> dict[str, Any] | None:
    with database() as connection:
        row = connection.execute(
            "SELECT * FROM import_jobs WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
    return _row_to_job(row) if row else None


def get_job(job_id: str) -> dict[str, Any] | None:
    with database() as connection:
        row = connection.execute("SELECT * FROM import_jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_job(row) if row else None


def create_job(idempotency_key: str, source_type: str, request_data: dict[str, Any]) -> dict[str, Any]:
    existing = get_job_by_key(idempotency_key)
    if existing:
        return existing
    job_id = str(uuid.uuid4())
    with database() as connection:
        connection.execute(
            """
            INSERT INTO import_jobs(id, idempotency_key, source_type, status, request_json)
            VALUES (?, ?, ?, 'running', ?)
            """,
            (job_id, idempotency_key, source_type, json.dumps(request_data, ensure_ascii=False)),
        )
    return get_job(job_id) or {"id": job_id, "status": "running"}


def complete_job(job_id: str, result: dict[str, Any]) -> dict[str, Any]:
    with database() as connection:
        connection.execute(
            """
            UPDATE import_jobs
            SET status = 'completed', result_json = ?, error_message = '', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (json.dumps(result, ensure_ascii=False), job_id),
        )
    return get_job(job_id) or {"id": job_id, "status": "completed", "result": result}


def fail_job(job_id: str, message: str) -> dict[str, Any]:
    with database() as connection:
        connection.execute(
            """
            UPDATE import_jobs
            SET status = 'failed', error_message = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (message[:1000], job_id),
        )
    return get_job(job_id) or {"id": job_id, "status": "failed", "error_message": message}


def _row_to_job(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "idempotency_key": row["idempotency_key"],
        "source_type": row["source_type"],
        "status": row["status"],
        "request": json.loads(row["request_json"] or "{}"),
        "result": json.loads(row["result_json"] or "{}"),
        "error_message": row["error_message"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
