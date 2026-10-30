from __future__ import annotations

import time

import click
from flask import Flask

from webhook_service.db import get_db, init_database
from webhook_service.queue import process_one_job


def register_commands(app: Flask) -> None:
    app.cli.add_command(init_db_command)
    app.cli.add_command(worker_command)


@click.command("init-db")
def init_db_command() -> None:
    """Create the SQLite schema."""
    init_database(get_db())
    click.echo("Database initialized.")


@click.command("worker")
@click.option("--once", is_flag=True, help="Process at most one ready job and exit.")
@click.option("--poll-interval", type=click.FloatRange(min=0.01), default=0.5, show_default=True)
@click.option("--lease-seconds", type=click.FloatRange(min=0.1), default=30.0, show_default=True)
@click.option("--backoff-seconds", type=click.FloatRange(min=0.0), default=1.0, show_default=True)
def worker_command(
    once: bool,
    poll_interval: float,
    lease_seconds: float,
    backoff_seconds: float,
) -> None:
    """Process queued jobs until interrupted."""
    while True:
        processed = process_one_job(
            get_db(),
            lease_seconds=lease_seconds,
            backoff_seconds=backoff_seconds,
        )
        if once:
            return
        if not processed:
            time.sleep(poll_interval)
