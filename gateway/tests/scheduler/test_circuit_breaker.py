"""Unit tests for CircuitBreaker."""

from unittest.mock import patch

from scheduler.tasks.circuit_breaker import CircuitBreaker

_MOD = "scheduler.tasks.circuit_breaker"


class TestCircuitBreaker:
    def test_closed_by_default(self):
        breaker = CircuitBreaker(failure_threshold=lambda: 3, pause_seconds=lambda: 60)
        assert breaker.is_open is False

    def test_stays_closed_below_the_threshold(self):
        breaker = CircuitBreaker(failure_threshold=lambda: 3, pause_seconds=lambda: 60)
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.is_open is False

    def test_opens_at_the_threshold(self):
        breaker = CircuitBreaker(failure_threshold=lambda: 3, pause_seconds=lambda: 60)
        breaker.record_failure()
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.is_open is True

    def test_a_success_resets_the_failure_streak(self):
        breaker = CircuitBreaker(failure_threshold=lambda: 3, pause_seconds=lambda: 60)
        breaker.record_failure()
        breaker.record_failure()
        breaker.record_success()
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.is_open is False

    def test_closes_again_after_the_pause_elapses(self):
        breaker = CircuitBreaker(failure_threshold=lambda: 1, pause_seconds=lambda: 60)
        with patch(f"{_MOD}.time.monotonic", side_effect=[100.0, 100.0, 200.0]):
            breaker.record_failure()  # opens at t=100
            assert breaker.is_open is True  # checked at t=100, still open
            assert breaker.is_open is False  # checked at t=200, pause elapsed

    def test_reopens_after_a_fresh_failure_streak_once_closed(self):
        breaker = CircuitBreaker(failure_threshold=lambda: 1, pause_seconds=lambda: 60)
        with patch(f"{_MOD}.time.monotonic", side_effect=[100.0, 100.0, 200.0, 200.0, 200.0]):
            breaker.record_failure()  # opens at t=100
            assert breaker.is_open is True  # t=100
            assert breaker.is_open is False  # t=200, closes and resets
            breaker.record_failure()  # opens again at t=200
            assert breaker.is_open is True  # t=200

    def test_threshold_change_takes_effect_immediately(self):
        """The whole point of accepting callables: an operator can raise the threshold
        via Config mid-run, without recreating the breaker, and it is re-read on the
        very next record_failure()."""
        threshold = 2
        breaker = CircuitBreaker(failure_threshold=lambda: threshold, pause_seconds=lambda: 60)

        breaker.record_failure()
        breaker.record_failure()
        assert breaker.is_open is True

        breaker._reset()  # pylint: disable=protected-access
        threshold = 5
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.is_open is False  # now needs 5, not 2

    def test_pause_change_takes_effect_immediately(self):
        """Same idea for pause_seconds: a shorter pause set mid-run closes the breaker
        sooner, without recreating it."""
        pause = 60
        breaker = CircuitBreaker(failure_threshold=lambda: 1, pause_seconds=lambda: pause)

        with patch(f"{_MOD}.time.monotonic", side_effect=[100.0, 100.0, 110.0]):
            breaker.record_failure()  # opens at t=100
            assert breaker.is_open is True  # t=100, still within the 60s pause
            pause = 5
            assert breaker.is_open is False  # t=110, now past the shortened 5s pause
