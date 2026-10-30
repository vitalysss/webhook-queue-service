from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from flask import Flask
from flask.testing import FlaskClient

from webhook_service import create_app
from webhook_service.db import get_db, init_database


@pytest.fixture()
def app(tmp_path: Path) -> Iterator[Flask]:
    application = create_app(
        {
            "TESTING": True,
            "DATABASE": str(tmp_path / "test.sqlite3"),
        }
    )
    with application.app_context():
        init_database(get_db())
    yield application


@pytest.fixture()
def client(app: Flask) -> FlaskClient:
    return app.test_client()


@pytest.fixture()
def valid_event() -> dict[str, object]:
    return {
        "event_id": "abc-123",
        "type": "payment_succeeded",
        "payload": {"amount": 1000},
    }
