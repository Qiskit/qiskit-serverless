"""Pytest fixtures for scheduler tests."""

import pytest

from scheduler import schedule
from scheduler.tasks.circuit_breaker import build_fleets_circuit_breaker


@pytest.fixture(autouse=True)
def fresh_code_engine_breaker(monkeypatch):
    """A closed CODE_ENGINE_BREAKER for every test."""
    monkeypatch.setattr(schedule, "CODE_ENGINE_BREAKER", build_fleets_circuit_breaker())
