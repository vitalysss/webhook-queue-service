from __future__ import annotations

from typing import Any


class UnsupportedEventTypeError(Exception):
    """Raised when no handler is registered for an event type."""


SUPPORTED_EVENT_TYPES = {"payment_succeeded", "payment_failed"}


def handle_event(event_type: str, payload: dict[str, Any], attempt: int) -> None:
    """Simulate a deterministic event handler.

    ``simulate_failure`` makes every attempt fail. ``fail_until_attempt`` is
    useful for demonstrating a transient failure without randomness.
    """
    if event_type not in SUPPORTED_EVENT_TYPES:
        raise UnsupportedEventTypeError(event_type)

    if payload.get("simulate_failure") is True:
        raise RuntimeError("simulated permanent handler failure")

    fail_until_attempt = payload.get("fail_until_attempt", 0)
    if isinstance(fail_until_attempt, int) and attempt <= fail_until_attempt:
        raise RuntimeError(f"simulated failure on attempt {attempt}")

    # A real service would call domain code here. The stub deliberately has no
    # external side effects, so retry behaviour remains deterministic in tests.
