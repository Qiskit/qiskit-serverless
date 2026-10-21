"""Prometheus collector for the exact worst duration of a scheduler loop and of each task."""

import threading
import time
from collections import defaultdict, deque

from prometheus_client import CollectorRegistry
from prometheus_client.metrics_core import GaugeMetricFamily
from prometheus_client.registry import Collector

WINDOW_SECONDS = 120


class DurationMaxCollector(Collector):
    """Keeps the samples of the last WINDOW_SECONDS and reports their maximum at scrape time. A histogram cannot tell
    the slowest event. The loop thread records and the HTTP server thread reads, so the samples sit behind a lock.
    The key is the task name, or None for the whole loop."""

    def __init__(self, registry: CollectorRegistry):
        self._lock = threading.Lock()
        self._samples: dict[str | None, deque] = defaultdict(deque)
        registry.register(self)

    def record(self, name: str | None, elapsed_seconds: float) -> None:
        """Record the duration of one task execution, or of one loop iteration when name is None."""
        with self._lock:
            now = time.monotonic()
            self._samples[name].append((now, elapsed_seconds))
            self._prune(name, now)

    def _prune(self, name: str | None, now: float) -> deque:
        samples = self._samples[name]
        while samples and now - samples[0][0] > WINDOW_SECONDS:
            samples.popleft()
        return samples

    def collect(self):
        loop = GaugeMetricFamily(
            "scheduler_loop_duration_max_seconds",
            f"Longest scheduler loop iteration among those recorded in the last {WINDOW_SECONDS} seconds.",
        )
        tasks = GaugeMetricFamily(
            "scheduler_task_duration_max_seconds",
            f"Longest execution of a scheduler task among those recorded in the last {WINDOW_SECONDS} seconds.",
            labels=["task_name"],
        )
        with self._lock:
            now = time.monotonic()
            for name in list(self._samples):
                samples = self._prune(name, now)
                if not samples:
                    del self._samples[name]
                elif name is None:
                    loop.add_metric([], max(value for _, value in samples))
                else:
                    tasks.add_metric([name], max(value for _, value in samples))
        yield loop
        yield tasks
