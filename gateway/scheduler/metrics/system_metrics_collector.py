import psutil
from prometheus_client import CollectorRegistry
from prometheus_client.metrics_core import GaugeMetricFamily
from prometheus_client.registry import Collector


class SystemMetricsCollector(Collector):
    """Custom collector for system metrics with lazy evaluation (that means the metrics are only computed
    when Prometheus scrapes the /metrics endpoint and not every second or every minute)"""

    def __init__(self, registry: CollectorRegistry):
        registry.register(self)

    def collect(self):
        # System CPU
        yield GaugeMetricFamily(
            "scheduler_system_cpu_percent",
            "CPU usage percentage",
            value=psutil.cpu_percent(),
        )

        # Memory and IO use bytes following the Prometheus best practices: https://prometheus.io/docs/practices/naming/
        mem = psutil.virtual_memory()
        yield GaugeMetricFamily(
            "scheduler_system_memory_used_bytes",
            "System memory used in bytes",
            value=mem.used,
        )
        yield GaugeMetricFamily(
            "scheduler_system_memory_percent",
            "System memory usage percentage",
            value=mem.percent,
        )

        # Network IO
        net = psutil.net_io_counters()
        yield GaugeMetricFamily(
            "scheduler_network_bytes_sent_total",
            "Total network bytes sent",
            value=net.bytes_sent,
        )
        yield GaugeMetricFamily(
            "scheduler_network_bytes_recv_total",
            "Total network bytes received",
            value=net.bytes_recv,
        )
