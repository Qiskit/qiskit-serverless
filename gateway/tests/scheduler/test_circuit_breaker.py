"""Unit tests for CircuitBreaker."""

from unittest.mock import patch

from scheduler.tasks.circuit_breaker import CircuitBreaker

_MOD = "scheduler.tasks.circuit_breaker"


class TestCircuitBreaker:
    def test_closed_by_default(self):
        breaker = CircuitBreaker(failure_threshold=3, pause_seconds=60)
        assert breaker.is_open is False

    def test_stays_closed_below_the_threshold(self):
        breaker = CircuitBreaker(failure_threshold=3, pause_seconds=60)
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.is_open is False

    def test_opens_at_the_threshold(self):
        breaker = CircuitBreaker(failure_threshold=3, pause_seconds=60)
        breaker.record_failure()
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.is_open is True

    def test_a_success_resets_the_failure_streak(self):
        breaker = CircuitBreaker(failure_threshold=3, pause_seconds=60)
        breaker.record_failure()
        breaker.record_failure()
        breaker.record_success()
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.is_open is False

    def test_closes_again_after_the_pause_elapses(self):
        breaker = CircuitBreaker(failure_threshold=1, pause_seconds=60)
        with patch(f"{_MOD}.time.monotonic", side_effect=[100.0, 100.0, 200.0]):
            breaker.record_failure()  # opens at t=100
            assert breaker.is_open is True  # checked at t=100, still open
            assert breaker.is_open is False  # checked at t=200, pause elapsed

    def test_reopens_after_a_fresh_failure_streak_once_closed(self):
        breaker = CircuitBreaker(failure_threshold=1, pause_seconds=60)
        with patch(f"{_MOD}.time.monotonic", side_effect=[100.0, 100.0, 200.0, 200.0, 200.0]):
            breaker.record_failure()  # opens at t=100
            assert breaker.is_open is True  # t=100
            assert breaker.is_open is False  # t=200, closes and resets
            breaker.record_failure()  # opens again at t=200
            assert breaker.is_open is True  # t=200
