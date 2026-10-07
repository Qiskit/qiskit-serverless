"""Pytest fixtures for scheduler tests."""

import pytest

from scheduler import schedule
from scheduler.tasks.circuit_breaker import build_fleets_circuit_breaker


@pytest.fixture(autouse=True)
def fresh_delete_breaker(monkeypatch):
    """A closed DELETE_BREAKER for every test."""
    monkeypatch.setattr(schedule, "DELETE_BREAKER", build_fleets_circuit_breaker())
