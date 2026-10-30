from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

from webhook_service.handlers import UnsupportedEventTypeError, handle_event

MAX_ATTEMPTS = 3
DEFAULT_LEASE_SECONDS = 30.0
DEFAULT_BACKOFF_SECONDS = 1.0


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    id: int
    event_type: str
    payload: dict[str, Any]
    attempt: int


def claim_next_job(
    connection: sqlite3.Connection,
    *,
    now: float | None = None,
    lease_seconds: float = DEFAULT_LEASE_SECONDS,
) -> ClaimedJob | None:
    current_time = time.time() if now is None else now

    connection.execute("BEGIN IMMEDIATE")
    try:
        # If a worker died during its final attempt, the expired lease must not
        # leave the job pending forever.
        connection.execute(
            """
            UPDATE jobs
            SET status = 'failed',
                locked_until = NULL,
                last_error = COALESCE(
                    last_error,
                    'worker lease expired after final attempt'
                ),
                updated_at = ?
            WHERE status = 'pending'
              AND attempt_count >= ?
              AND locked_until IS NOT NULL
              AND locked_until <= ?
            """,
            (current_time, MAX_ATTEMPTS, current_time),
        )

        row = connection.execute(
            """
            SELECT jobs.id
            FROM jobs
            WHERE jobs.status = 'pending'
              AND jobs.attempt_count < ?
              AND jobs.available_at <= ?
              AND (jobs.locked_until IS NULL OR jobs.locked_until <= ?)
            ORDER BY jobs.id
            LIMIT 1
            """,
            (MAX_ATTEMPTS, current_time, current_time),
        ).fetchone()

        if row is None:
            connection.commit()
            return None

        job_id = int(row["id"])
        connection.execute(
            """
            UPDATE jobs
            SET attempt_count = attempt_count + 1,
                locked_until = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (current_time + lease_seconds, current_time, job_id),
        )
        claimed = connection.execute(
            """
            SELECT jobs.id, jobs.attempt_count, events.event_type,
                   events.payload_json
            FROM jobs
            JOIN events ON events.id = jobs.event_id
            WHERE jobs.id = ?
            """,
            (job_id,),
        ).fetchone()
        connection.commit()
    except Exception:
        connection.rollback()
        raise

    if claimed is None:  # Defensive: the row cannot disappear in this schema.
        return None

    payload = json.loads(claimed["payload_json"])
    return ClaimedJob(
        id=int(claimed["id"]),
        event_type=str(claimed["event_type"]),
        payload=payload,
        attempt=int(claimed["attempt_count"]),
    )


def process_one_job(
    connection: sqlite3.Connection,
    *,
    now: float | None = None,
    lease_seconds: float = DEFAULT_LEASE_SECONDS,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
) -> bool:
    current_time = time.time() if now is None else now
    job = claim_next_job(
        connection,
        now=current_time,
        lease_seconds=lease_seconds,
    )
    if job is None:
        return False

    try:
        handle_event(job.event_type, job.payload, job.attempt)
    except UnsupportedEventTypeError:
        _finish_job(connection, job.id, "skipped", current_time)
    except Exception as error:  # The worker boundary owns retry decisions.
        _record_failure(
            connection,
            job,
            error,
            current_time,
            backoff_seconds,
        )
    else:
        _finish_job(connection, job.id, "success", current_time)

    return True


def _finish_job(
    connection: sqlite3.Connection,
    job_id: int,
    status: str,
    now: float,
) -> None:
    connection.execute(
        """
        UPDATE jobs
        SET status = ?, locked_until = NULL, last_error = NULL, updated_at = ?
        WHERE id = ?
        """,
        (status, now, job_id),
    )
    connection.commit()


def _record_failure(
    connection: sqlite3.Connection,
    job: ClaimedJob,
    error: Exception,
    now: float,
    backoff_seconds: float,
) -> None:
    safe_error = str(error)[:500]
    if job.attempt >= MAX_ATTEMPTS:
        connection.execute(
            """
            UPDATE jobs
            SET status = 'failed', locked_until = NULL,
                last_error = ?, updated_at = ?
            WHERE id = ?
            """,
            (safe_error, now, job.id),
        )
    else:
        delay = backoff_seconds * (2 ** (job.attempt - 1))
        connection.execute(
            """
            UPDATE jobs
            SET status = 'pending', available_at = ?, locked_until = NULL,
                last_error = ?, updated_at = ?
            WHERE id = ?
            """,
            (now + delay, safe_error, now, job.id),
        )
    connection.commit()
