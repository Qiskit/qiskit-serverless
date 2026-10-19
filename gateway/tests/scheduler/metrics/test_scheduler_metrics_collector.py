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


class TestFleetsAndCloudCallMetrics:
    def test_the_fleets_breaker_gauge_is_per_region(self):
        from prometheus_client import CollectorRegistry
        from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics

        registry = CollectorRegistry()
        metrics = SchedulerMetrics(registry)
        metrics.set_fleets_breaker_open(True, "us-east")
        metrics.set_fleets_breaker_open(False, None)

        assert registry.get_sample_value("scheduler_fleets_breaker_open", {"region": "us-east"}) == 1
        assert registry.get_sample_value("scheduler_fleets_breaker_open", {"region": "none"}) == 0

    def test_the_cloud_call_histograms_take_the_recorder_labels(self):
        from prometheus_client import CollectorRegistry
        from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics

        registry = CollectorRegistry()
        metrics = SchedulerMetrics(registry)
        metrics.observe_code_engine_call("POST /projects/{project_id}/fleets", "429", 0.2)
        metrics.observe_cos_call("PutObject", "200", 0.2)

        ce = {"endpoint": "POST /projects/{project_id}/fleets", "status": "429"}
        cos = {"operation": "PutObject", "status": "200"}
        assert registry.get_sample_value("scheduler_code_engine_request_duration_seconds_count", ce) == 1
        assert registry.get_sample_value("scheduler_cos_request_duration_seconds_count", cos) == 1

    def test_a_ten_minute_task_lands_below_inf(self):
        from prometheus_client import CollectorRegistry
        from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics

        registry = CollectorRegistry()
        metrics = SchedulerMetrics(registry)
        metrics.observe_task_duration("ScheduleFleetsJobs", 600)

        bucket = registry.get_sample_value(
            "scheduler_task_duration_seconds_bucket", {"task_name": "ScheduleFleetsJobs", "le": "600.0"}
        )
        assert bucket == 1
