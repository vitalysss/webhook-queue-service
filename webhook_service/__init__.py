from __future__ import annotations

from pathlib import Path
from typing import Any

from flask import Flask

from webhook_service.api import api
from webhook_service.cli import register_commands
from webhook_service.db import close_db


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        DATABASE=str(Path(app.instance_path) / "events.sqlite3"),
        MAX_CONTENT_LENGTH=64 * 1024,
    )

    if test_config is not None:
        app.config.update(test_config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    app.teardown_appcontext(close_db)
    app.register_blueprint(api)
    register_commands(app)

    return app
