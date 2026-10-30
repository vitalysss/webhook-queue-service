from __future__ import annotations

from flask import Flask
from flask.testing import FlaskClient

from webhook_service.db import get_db
from webhook_service.queue import process_one_job


def test_stats_counts_events_and_job_statuses(
    app: Flask,
    client: FlaskClient,
) -> None:
    first = {
        "event_id": "one",
        "type": "payment_succeeded",
        "payload": {},
    }
    second = {
        "event_id": "two",
        "type": "payment_failed",
        "payload": {},
    }
    client.post("/webhook", json=first)
    client.post("/webhook", json=second)

    with app.app_context():
        ready_at = float(
            get_db().execute("SELECT MIN(available_at) FROM jobs").fetchone()[0]
        )
        assert process_one_job(get_db(), now=ready_at + 1)

    response = client.get("/stats")

    assert response.status_code == 200
    assert response.get_json() == {
        "events_by_type": {"payment_failed": 1, "payment_succeeded": 1},
        "jobs_by_status": {"pending": 1, "success": 1},
    }
