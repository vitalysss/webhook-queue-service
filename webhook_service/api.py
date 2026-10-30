from __future__ import annotations

import json
import time
from typing import Any

from flask import Blueprint, Response, jsonify, request

from webhook_service.db import get_db

api = Blueprint("api", __name__)


def _error(message: str, status: int, details: dict[str, str] | None = None) -> tuple[Response, int]:
    body: dict[str, Any] = {"error": {"message": message}}
    if details:
        body["error"]["details"] = details
    return jsonify(body), status


def _validate_event(body: Any) -> tuple[dict[str, Any] | None, dict[str, str]]:
    if not isinstance(body, dict):
        return None, {"body": "JSON body must be an object"}

    errors: dict[str, str] = {}
    event_id = body.get("event_id")
    event_type = body.get("type")
    payload = body.get("payload")

    if not isinstance(event_id, str) or not event_id.strip():
        errors["event_id"] = "must be a non-empty string"
    elif len(event_id) > 128:
        errors["event_id"] = "must be at most 128 characters"

    if not isinstance(event_type, str) or not event_type.strip():
        errors["type"] = "must be a non-empty string"
    elif len(event_type) > 128:
        errors["type"] = "must be at most 128 characters"

    if not isinstance(payload, dict):
        errors["payload"] = "must be a JSON object"

    if errors:
        return None, errors

    return {
        "event_id": event_id.strip(),
        "event_type": event_type.strip(),
        "payload": payload,
    }, {}


@api.post("/webhook")
def receive_webhook() -> tuple[Response, int]:
    if not request.is_json:
        return _error("Content-Type must be application/json", 415)

    body = request.get_json(silent=True)
    event, errors = _validate_event(body)
    if event is None:
        return _error("Invalid webhook body", 400, errors)

    connection = get_db()
    now = time.time()
    connection.execute("BEGIN IMMEDIATE")
    try:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO events (
                event_id, event_type, payload_json, created_at
            ) VALUES (?, ?, ?, ?)
            """,
            (
                event["event_id"],
                event["event_type"],
                json.dumps(event["payload"], ensure_ascii=False, separators=(",", ":")),
                now,
            ),
        )
        created = cursor.rowcount == 1
        if created:
            database_event_id = int(cursor.lastrowid)
            connection.execute(
                """
                INSERT INTO jobs (
                    event_id, status, attempt_count, available_at,
                    locked_until, created_at, updated_at
                ) VALUES (?, 'pending', 0, ?, NULL, ?, ?)
                """,
                (database_event_id, now, now, now),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise

    status = "accepted" if created else "duplicate"
    return jsonify({"event_id": event["event_id"], "status": status}), 200


@api.get("/stats")
def stats() -> Response:
    connection = get_db()
    event_rows = connection.execute(
        """
        SELECT event_type, COUNT(*) AS count
        FROM events
        GROUP BY event_type
        ORDER BY event_type
        """
    ).fetchall()
    job_rows = connection.execute(
        """
        SELECT status, COUNT(*) AS count
        FROM jobs
        GROUP BY status
        ORDER BY status
        """
    ).fetchall()
    return jsonify(
        {
            "events_by_type": {
                str(row["event_type"]): int(row["count"]) for row in event_rows
            },
            "jobs_by_status": {
                str(row["status"]): int(row["count"]) for row in job_rows
            },
        }
    )


@api.app_errorhandler(413)
def payload_too_large(_error: Exception) -> tuple[Response, int]:
    return _error_response_for_large_payload()


def _error_response_for_large_payload() -> tuple[Response, int]:
    return _error("Request body is too large", 413)
