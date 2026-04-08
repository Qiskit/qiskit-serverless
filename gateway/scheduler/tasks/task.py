"""Base contract for scheduler tasks."""

from abc import ABC, abstractmethod


class SchedulerTask(ABC):
    """Abstract task executed by the scheduler loop."""

    @property
    def name(self) -> str:
        """Return task name for logs/metrics."""
        return self.__class__.__name__

    @abstractmethod
    def run(self):
        """Execute one scheduler cycle for this task."""
