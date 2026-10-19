"""Export the state of the Code Engine circuit breakers."""

from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from scheduler.schedule import CodeEngineBreakers
from .task import SchedulerTask


class ExportFleetsBreakers(SchedulerTask):
    """Set the breaker gauge of every region, after every task that calls Code Engine."""

    def __init__(self, metrics: SchedulerMetrics, breakers: CodeEngineBreakers):
        self.metrics = metrics
        self.breakers = breakers

    def run(self):
        for region, breaker in self.breakers.breakers.items():
            self.metrics.set_fleets_breaker_open(breaker.is_open, region)
