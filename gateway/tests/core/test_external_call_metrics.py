"""Unit tests for the scheduler operation duration metric."""

import pytest
import requests
from prometheus_client import CollectorRegistry

from core import external_call_metrics
from core.external_call_metrics import FLEET_STATUS_READ, observe_operation


@pytest.fixture(name="registry")
def registry_fixture():
    registry = CollectorRegistry()
    external_call_metrics.enable(registry)
    yield registry
    external_call_metrics.disable()


def _count(registry: CollectorRegistry, operation: str, status: str) -> float:
    return (
        registry.get_sample_value(
            "scheduler_operation_duration_seconds_count", {"operation": operation, "status": status}
        )
        or 0.0
    )


class TestObserveOperation:
    """Each operation is recorded once, with the status it ended with."""

    def test_a_status_set_by_the_caller_replaces_the_one_from_how_the_block_ended(self, registry):
        with observe_operation(FLEET_STATUS_READ) as observation:
            observation.status = "429"

        assert _count(registry, FLEET_STATUS_READ, "429") == 1
        assert _count(registry, FLEET_STATUS_READ, "ok") == 0

    def test_an_operation_that_returns_is_ok(self, registry):
        with observe_operation(FLEET_STATUS_READ):
            pass

        assert _count(registry, FLEET_STATUS_READ, "ok") == 1

    def test_a_timeout_is_told_apart_from_another_error_and_still_raised(self, registry):
        with pytest.raises(requests.ReadTimeout):
            with observe_operation(FLEET_STATUS_READ):
                raise requests.ReadTimeout("slow")
        with pytest.raises(ValueError):
            with observe_operation(FLEET_STATUS_READ):
                raise ValueError("boom")

        assert _count(registry, FLEET_STATUS_READ, "timeout") == 1
        assert _count(registry, FLEET_STATUS_READ, "error") == 1

    def test_nothing_is_recorded_until_the_scheduler_enables_it(self):
        external_call_metrics.disable()
        registry = CollectorRegistry()

        with observe_operation(FLEET_STATUS_READ):
            pass

        assert _count(registry, FLEET_STATUS_READ, "ok") == 0
