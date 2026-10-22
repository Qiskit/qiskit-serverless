"""Export the state of the Fleets circuit breakers."""

from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from scheduler.schedule import FleetsBreakers
from .task import SchedulerTask


class ExportFleetsBreakers(SchedulerTask):
    """Set the breaker gauge of every dependency and region, after every task that uses them."""

    def __init__(self, metrics: SchedulerMetrics, breakers: FleetsBreakers):
        self.metrics = metrics
        self.breakers = breakers

    def run(self):
        for dependency, registry in self.breakers.registries().items():
            for region, breaker in registry.breakers.items():
                self.metrics.set_fleets_breaker_open(breaker.is_open, dependency, region)
