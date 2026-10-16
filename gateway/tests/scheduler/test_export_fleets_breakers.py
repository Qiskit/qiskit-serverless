"""Unit tests for ExportFleetsBreakers."""

from unittest.mock import MagicMock, call

import pytest

from core.models import Config
from scheduler.schedule import CodeEngineBreakers
from scheduler.tasks.circuit_breaker import DEFAULT_FAILURE_THRESHOLD
from scheduler.tasks.export_fleets_breakers import ExportFleetsBreakers


@pytest.mark.django_db
def test_the_breaker_gauge_is_set_for_each_region():
    Config.add_defaults()
    breakers = CodeEngineBreakers()
    for _ in range(DEFAULT_FAILURE_THRESHOLD):
        breakers.get_breaker("us-east").record_failure()
    breakers.get_breaker("eu-de")
    metrics = MagicMock()

    ExportFleetsBreakers(metrics, breakers).run()

    metrics.set_fleets_breaker_open.assert_has_calls([call(True, "us-east"), call(False, "eu-de")], any_order=True)
