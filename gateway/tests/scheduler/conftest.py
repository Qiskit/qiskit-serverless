"""Pytest fixtures for scheduler tests."""

import pytest

from core.config_key import ConfigKey
from scheduler import schedule
from scheduler.tasks.circuit_breaker import CircuitBreaker


@pytest.fixture(autouse=True)
def fresh_code_engine_breaker(monkeypatch):
    """A closed CODE_ENGINE_BREAKER for every test."""
    monkeypatch.setattr(
        schedule,
        "CODE_ENGINE_BREAKER",
        CircuitBreaker(ConfigKey.FLEETS_BREAKER_FAILURES, ConfigKey.FLEETS_BREAKER_PAUSE_SECONDS),
    )
