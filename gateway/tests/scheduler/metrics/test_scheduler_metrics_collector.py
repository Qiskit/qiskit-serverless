"""Unit tests for SchedulerMetrics."""


class TestOutboxBreakerOpenIsPerChannel:
    """The outbox circuit breaker gauge must be labeled per channel."""

    def test_set_outbox_breaker_open_requires_a_channel_label(self):
        from prometheus_client import CollectorRegistry
        from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics

        metrics = SchedulerMetrics(CollectorRegistry())

        metrics.set_outbox_breaker_open(True, channel="billing")
        metrics.set_outbox_breaker_open(False, channel="workload")

        value_billing = metrics.outbox_breaker_open.labels(channel="billing")._value.get()
        value_workload = metrics.outbox_breaker_open.labels(channel="workload")._value.get()
        assert value_billing == 1
        assert value_workload == 0

    def test_increment_outbox_license_fee_irrecoverable_no_longer_exists(self):
        from prometheus_client import CollectorRegistry
        from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics

        metrics = SchedulerMetrics(CollectorRegistry())

        assert not hasattr(metrics, "increment_outbox_license_fee_irrecoverable")


class TestLoopDurationBuckets:
    """Loop and task durations must be measurable well beyond 10 s."""

    def test_loop_and_task_histograms_reach_300_seconds(self):
        from prometheus_client import CollectorRegistry
        from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics

        metrics = SchedulerMetrics(CollectorRegistry())

        assert 300.0 in metrics.loop_duration._upper_bounds
        assert 300.0 in metrics.task_duration.labels(task_name="x")._upper_bounds
