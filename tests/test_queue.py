from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from flask import Flask
from flask.testing import FlaskClient

from webhook_service.db import connect_database, get_db
from webhook_service.queue import claim_next_job, process_one_job


def _ready_at(app: Flask) -> float:
    with app.app_context():
        row = get_db().execute("SELECT available_at FROM jobs").fetchone()
        return float(row["available_at"])


def test_successful_job_is_processed(
    app: Flask,
    client: FlaskClient,
    valid_event: dict[str, object],
) -> None:
    client.post("/webhook", json=valid_event)
    ready_at = _ready_at(app)

    with app.app_context():
        assert process_one_job(get_db(), now=ready_at) is True
        row = get_db().execute(
            "SELECT status, attempt_count FROM jobs"
        ).fetchone()
        assert dict(row) == {"status": "success", "attempt_count": 1}


def test_failure_retries_with_backoff_then_becomes_failed(
    app: Flask,
    client: FlaskClient,
) -> None:
    client.post(
        "/webhook",
        json={
            "event_id": "always-fails",
            "type": "payment_succeeded",
            "payload": {"simulate_failure": True},
        },
    )
    ready_at = _ready_at(app)

    with app.app_context():
        connection = get_db()
        assert process_one_job(connection, now=ready_at, backoff_seconds=10)
        assert process_one_job(connection, now=ready_at + 9, backoff_seconds=10) is False
        assert process_one_job(connection, now=ready_at + 10, backoff_seconds=10)
        assert process_one_job(connection, now=ready_at + 29, backoff_seconds=10) is False
        assert process_one_job(connection, now=ready_at + 30, backoff_seconds=10)

        row = connection.execute(
            "SELECT status, attempt_count, locked_until FROM jobs"
        ).fetchone()
        assert row["status"] == "failed"
        assert row["attempt_count"] == 3
        assert row["locked_until"] is None


def test_expired_final_lease_is_recovered_as_failed(
    app: Flask,
    client: FlaskClient,
    valid_event: dict[str, object],
) -> None:
    client.post("/webhook", json=valid_event)
    ready_at = _ready_at(app)

    with app.app_context():
        connection = get_db()
        assert claim_next_job(connection, now=ready_at, lease_seconds=5) is not None
        assert claim_next_job(connection, now=ready_at + 5, lease_seconds=5) is not None
        assert claim_next_job(connection, now=ready_at + 10, lease_seconds=5) is not None

        # Simulate three worker crashes: the next poll expires the final lease.
        assert claim_next_job(connection, now=ready_at + 15, lease_seconds=5) is None
        row = connection.execute(
            "SELECT status, attempt_count, locked_until FROM jobs"
        ).fetchone()
        assert row["status"] == "failed"
        assert row["attempt_count"] == 3
        assert row["locked_until"] is None


def test_unknown_event_type_is_skipped(app: Flask, client: FlaskClient) -> None:
    client.post(
        "/webhook",
        json={"event_id": "unknown", "type": "something_new", "payload": {}},
    )
    ready_at = _ready_at(app)

    with app.app_context():
        assert process_one_job(get_db(), now=ready_at)
        assert get_db().execute("SELECT status FROM jobs").fetchone()[0] == "skipped"


def test_two_workers_cannot_claim_the_same_job(
    app: Flask,
    client: FlaskClient,
    valid_event: dict[str, object],
) -> None:
    client.post("/webhook", json=valid_event)
    ready_at = _ready_at(app)
    database_path = app.config["DATABASE"]
    barrier = Barrier(2)

    def claim() -> bool:
        connection = connect_database(database_path)
        try:
            barrier.wait()
            return claim_next_job(connection, now=ready_at) is not None
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _number: claim(), range(2)))

    assert sorted(results) == [False, True]
    with app.app_context():
        assert get_db().execute(
            "SELECT attempt_count FROM jobs"
        ).fetchone()[0] == 1
