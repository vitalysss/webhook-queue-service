from __future__ import annotations

from flask import Flask
from flask.testing import FlaskClient

from webhook_service.db import get_db


def test_duplicate_webhook_creates_one_event_and_one_job(
    app: Flask,
    client: FlaskClient,
    valid_event: dict[str, object],
) -> None:
    first = client.post("/webhook", json=valid_event)
    second = client.post("/webhook", json=valid_event)

    assert first.status_code == 200
    assert first.get_json()["status"] == "accepted"
    assert second.status_code == 200
    assert second.get_json()["status"] == "duplicate"

    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
        assert get_db().execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1


def test_webhook_rejects_invalid_body(client: FlaskClient) -> None:
    response = client.post(
        "/webhook",
        json={"event_id": "", "type": 42, "payload": []},
    )

    assert response.status_code == 400
    assert response.get_json() == {
        "error": {
            "message": "Invalid webhook body",
            "details": {
                "event_id": "must be a non-empty string",
                "payload": "must be a JSON object",
                "type": "must be a non-empty string",
            },
        }
    }


def test_webhook_requires_json_content_type(client: FlaskClient) -> None:
    response = client.post("/webhook", data="not json", content_type="text/plain")

    assert response.status_code == 415
    assert response.get_json()["error"]["message"] == (
        "Content-Type must be application/json"
    )


def test_webhook_rejects_malformed_json(client: FlaskClient) -> None:
    response = client.post(
        "/webhook",
        data='{"event_id":',
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["message"] == "Invalid webhook body"
