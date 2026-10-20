"""Prometheus collector for the exact worst duration of a scheduler loop and of each task."""

import threading
import time
from collections import defaultdict, deque

from prometheus_client import CollectorRegistry
from prometheus_client.metrics_core import GaugeMetricFamily
from prometheus_client.registry import Collector

WINDOW_SECONDS = 120


class DurationMaxCollector(Collector):
    """Keeps the samples of the last WINDOW_SECONDS and reports their maximum at scrape time.

    A histogram cannot tell the slowest event, and its last bucket hides anything longer than the top bound.
    Samples are recorded by the scheduler loop thread and read by the HTTP server thread, so they sit behind a lock.
    """

    def __init__(self, registry: CollectorRegistry):
        self._lock = threading.Lock()
        self._loop: deque = deque()
        self._tasks: dict[str, deque] = defaultdict(deque)
        registry.register(self)

    def record_loop(self, elapsed_seconds: float) -> None:
        """Record the duration of one loop iteration."""
        with self._lock:
            self._add(self._loop, elapsed_seconds)

    def record_task(self, task_name: str, elapsed_seconds: float) -> None:
        """Record the duration of one task execution."""
        with self._lock:
            self._add(self._tasks[task_name], elapsed_seconds)

    @staticmethod
    def _add(samples: deque, elapsed_seconds: float) -> None:
        now = time.monotonic()
        samples.append((now, elapsed_seconds))
        DurationMaxCollector._prune(samples, now)

    @staticmethod
    def _prune(samples: deque, now: float) -> None:
        while samples and now - samples[0][0] > WINDOW_SECONDS:
            samples.popleft()

    @staticmethod
    def _max(samples: deque, now: float) -> float | None:
        DurationMaxCollector._prune(samples, now)
        return max((value for _, value in samples), default=None)

    def collect(self):
        loop_gauge = GaugeMetricFamily(
            "scheduler_loop_duration_max_seconds",
            f"Longest scheduler loop iteration among those recorded in the last {WINDOW_SECONDS} seconds.",
        )
        task_gauge = GaugeMetricFamily(
            "scheduler_task_duration_max_seconds",
            f"Longest execution of a scheduler task among those recorded in the last {WINDOW_SECONDS} seconds.",
            labels=["task_name"],
        )
        with self._lock:
            now = time.monotonic()
            loop_max = self._max(self._loop, now)
            if loop_max is not None:
                loop_gauge.add_metric([], loop_max)
            for task_name, samples in self._tasks.items():
                task_max = self._max(samples, now)
                if task_max is not None:
                    task_gauge.add_metric([task_name], task_max)
        yield loop_gauge
        yield task_gauge
