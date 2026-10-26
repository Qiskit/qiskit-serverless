"""Samples the driver's own CPU and pauses once a second, to tell a slow driver from a slow gateway."""

import json
import resource
import threading
import time
from pathlib import Path

from .progress import Background

INTERVAL_SECONDS = 1.0


def _cpu_seconds() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_utime + usage.ru_stime


class HealthSampler(Background):
    """Writes health.jsonl: CPU as a share of one core, how late the sampler woke, and wall minus monotonic drift."""

    def __init__(self, path: Path):
        super().__init__()
        self._path = path

    def _loop(self) -> None:
        wall, mono, cpu = time.time(), time.monotonic(), _cpu_seconds()
        drift0 = wall - mono
        with self._path.open("a") as file:
            while not self._stop.wait(INTERVAL_SECONDS):
                now_wall, now_mono, now_cpu = time.time(), time.monotonic(), _cpu_seconds()
                elapsed = now_mono - mono
                row = {
                    "t": now_wall,
                    "cpu_percent": 100 * (now_cpu - cpu) / elapsed if elapsed > 0 else 0,
                    "late_seconds": max(0.0, elapsed - INTERVAL_SECONDS),
                    # the monotonic clock stops while a Mac sleeps, so a sleep shows up as drift
                    "drift_seconds": (now_wall - now_mono) - drift0,
                    "threads": threading.active_count(),
                }
                file.write(json.dumps(row) + "\n")
                file.flush()
                wall, mono, cpu = now_wall, now_mono, now_cpu
