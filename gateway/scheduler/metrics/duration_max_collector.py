"""Prometheus collector for the exact worst duration of each scheduler loop and of each task."""

import threading
import time
from collections import defaultdict, deque

from prometheus_client import CollectorRegistry
from prometheus_client.metrics_core import GaugeMetricFamily
from prometheus_client.registry import Collector

WINDOW_SECONDS = 120


class DurationMaxCollector(Collector):
    """Keeps the samples of the last WINDOW_SECONDS and reports their maximum at scrape time. A histogram cannot tell
    the slowest event. The loop threads record and the HTTP server thread reads, so the samples sit behind a lock.
    Tasks are keyed by task name and loops by loop name, in separate dicts so a loop and a task can share a name."""

    def __init__(self, registry: CollectorRegistry):
        self._lock = threading.Lock()
        self._tasks: dict[str, deque] = defaultdict(deque)
        self._loops: dict[str, deque] = defaultdict(deque)
        registry.register(self)

    def record(self, name: str, elapsed_seconds: float) -> None:
        """Record the duration of one task execution."""
        self._record(self._tasks, name, elapsed_seconds)

    def record_loop(self, loop: str, elapsed_seconds: float) -> None:
        """Record the duration of one iteration of a loop."""
        self._record(self._loops, loop, elapsed_seconds)

    def _record(self, group: dict[str, deque], name: str, elapsed_seconds: float) -> None:
        with self._lock:
            now = time.monotonic()
            group[name].append((now, elapsed_seconds))
            self._prune(group, name, now)

    @staticmethod
    def _prune(group: dict[str, deque], name: str, now: float) -> deque:
        samples = group[name]
        while samples and now - samples[0][0] > WINDOW_SECONDS:
            samples.popleft()
        return samples

    def _maximums(self, group: dict[str, deque], now: float) -> dict[str, float]:
        """The worst duration of each name still inside the window. Call it with the lock held."""
        maximums = {}
        for name in list(group):
            samples = self._prune(group, name, now)
            if samples:
                maximums[name] = max(value for _, value in samples)
            else:
                del group[name]
        return maximums

    def collect(self):
        loops = GaugeMetricFamily(
            "scheduler_loop_duration_max_seconds",
            f"Longest iteration of a scheduler loop among those recorded in the last {WINDOW_SECONDS} seconds.",
            labels=["loop"],
        )
        tasks = GaugeMetricFamily(
            "scheduler_task_duration_max_seconds",
            f"Longest execution of a scheduler task among those recorded in the last {WINDOW_SECONDS} seconds.",
            labels=["task_name"],
        )
        with self._lock:
            now = time.monotonic()
            loop_maximums = self._maximums(self._loops, now)
            task_maximums = self._maximums(self._tasks, now)
        for loop, value in loop_maximums.items():
            loops.add_metric([loop], value)
        for task, value in task_maximums.items():
            tasks.add_metric([task], value)
        yield loops
        yield tasks
