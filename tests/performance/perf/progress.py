"""A live line every 10 s with how many users are in each state."""

import threading
from collections import Counter

INTERVAL_SECONDS = 10
# print the counts at least this often, even when they do not change
HEARTBEAT_SECONDS = 60


class Background:
    """Start runs _loop on its own thread. _loop returns when self._stop is set."""

    def __init__(self):
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        """Start the thread."""
        self._thread.start()

    def stop(self) -> None:
        """Stop the thread and wait for it."""
        self._stop.set()
        self._thread.join()

    def _loop(self) -> None:
        raise NotImplementedError


class Progress(Background):
    """Prints the counts of a run until it is stopped."""

    def __init__(self, results, log):
        super().__init__()
        self._results = results
        self._log = log

    def stop(self) -> None:
        """Stop printing, after one last line."""
        super().stop()
        self._log(self.line())

    def line(self) -> str:
        """One line of counts."""
        counts: Counter = Counter()
        for result in self._results:
            if result.error:
                counts["errors"] += 1
            elif result.final_status:
                counts[result.final_status] += 1
            elif result.job_id:
                counts[result.statuses[-1][1] if result.statuses else "submitted"] += 1
            else:
                counts["starting"] += 1
        failed_polls = sum(len(result.poll_errors) for result in self._results)
        line = "progress " + " ".join(f"{name}={count}" for name, count in sorted(counts.items()))
        return f"{line} failed_polls={failed_polls}" if failed_polls else line

    def _loop(self) -> None:
        last, quiet = None, 0.0
        while not self._stop.wait(INTERVAL_SECONDS):
            line, quiet = self.line(), quiet + INTERVAL_SECONDS
            if line != last or quiet >= HEARTBEAT_SECONDS:
                self._log(line)
                last, quiet = line, 0.0
