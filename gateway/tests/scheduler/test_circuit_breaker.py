"""Unit tests for CircuitBreaker."""

from unittest.mock import patch

import pytest

from core.config_key import ConfigKey
from core.models import Config
from scheduler.tasks.circuit_breaker import CircuitBreaker

pytestmark = pytest.mark.django_db

_MOD = "scheduler.tasks.circuit_breaker"
_FAILURES = ConfigKey.OUTBOX_KAFKA_CHANNEL_BREAKER_FAILURES
_PAUSE = ConfigKey.OUTBOX_KAFKA_CHANNEL_BREAKER_PAUSE_SECONDS


def _breaker(threshold=3, pause=60) -> CircuitBreaker:
    Config.add_defaults()
    Config.set(_FAILURES, str(threshold))
    Config.set(_PAUSE, str(pause))
    return CircuitBreaker(_FAILURES, _PAUSE)


class TestCircuitBreaker:
    def test_closed_by_default(self):
        breaker = _breaker(3)
        assert breaker.is_open is False

    def test_stays_closed_below_the_threshold(self):
        breaker = _breaker(3)
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.is_open is False

    def test_opens_at_the_threshold(self):
        breaker = _breaker(3)
        breaker.record_failure()
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.is_open is True

    def test_a_success_resets_the_failure_streak(self):
        breaker = _breaker(3)
        breaker.record_failure()
        breaker.record_failure()
        breaker.record_success()
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.is_open is False

    def test_closes_again_after_the_pause_elapses(self):
        breaker = _breaker(1)
        with patch(f"{_MOD}.time.monotonic", side_effect=[100.0, 100.0, 200.0]):
            breaker.record_failure()  # opens at t=100
            assert breaker.is_open is True  # checked at t=100, still open
            assert breaker.is_open is False  # checked at t=200, pause elapsed

    def test_reopens_after_a_fresh_failure_streak_once_closed(self):
        breaker = _breaker(1)
        with patch(f"{_MOD}.time.monotonic", side_effect=[100.0, 100.0, 200.0, 200.0, 200.0]):
            breaker.record_failure()  # opens at t=100
            assert breaker.is_open is True  # t=100
            assert breaker.is_open is False  # t=200, closes and resets
            breaker.record_failure()  # opens again at t=200
            assert breaker.is_open is True  # t=200

    def test_threshold_change_takes_effect_immediately(self):
        """An operator can raise the threshold via Config mid-run, without recreating the breaker, and it is
        re-read on the very next record_failure()."""
        breaker = _breaker(threshold=2)

        breaker.record_failure()
        breaker.record_failure()
        assert breaker.is_open is True

        breaker._reset()  # pylint: disable=protected-access
        Config.set(_FAILURES, "5")
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.is_open is False  # now needs 5, not 2

    def test_pause_change_takes_effect_immediately(self):
        """Same idea for the pause: a shorter one set mid-run closes the breaker sooner, without recreating it."""
        breaker = _breaker(threshold=1, pause=60)
        clock = [100.0]

        with patch(f"{_MOD}.time.monotonic", side_effect=lambda: clock[0]):
            breaker.record_failure()  # opens at t=100
            assert breaker.is_open is True  # t=100, still within the 60s pause
            Config.set(_PAUSE, "5")
            clock[0] = 110.0
            assert breaker.is_open is False  # t=110, now past the shortened 5s pause


class TestAfterThePause:
    def test_it_takes_a_whole_new_failure_streak_to_open_again(self):
        clock = [100.0]
        breaker = _breaker(threshold=3)
        with patch(f"{_MOD}.time.monotonic", side_effect=lambda: clock[0]):
            for _ in range(3):
                breaker.record_failure()
            assert breaker.is_open is True
            clock[0] = 200.0
            assert breaker.is_open is False  # the pause elapsed

            breaker.record_failure()
            breaker.record_failure()
            assert breaker.is_open is False  # one failure short of a new streak
            breaker.record_failure()
            assert breaker.is_open is True
