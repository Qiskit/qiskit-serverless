"""Hook that reports the time of each Code Engine and COS call. Only the scheduler sets a recorder."""

from __future__ import annotations

from typing import Protocol


class CallRecorder(Protocol):
    """Receives one sample per Code Engine or COS call."""

    def observe_code_engine_call(self, endpoint: str, status: str, seconds: float) -> None:
        """Record one Code Engine API call."""

    def observe_cos_call(self, operation: str, status: str, seconds: float) -> None:
        """Record one COS call."""


_RECORDER: CallRecorder | None = None


def set_recorder(recorder: CallRecorder | None) -> None:
    """Set the process-wide recorder, or remove it with None."""
    global _RECORDER  # pylint: disable=global-statement
    _RECORDER = recorder


def observe_code_engine(endpoint: str, status: str, seconds: float) -> None:
    """Report one Code Engine call, if a recorder is set."""
    if _RECORDER is not None:
        _RECORDER.observe_code_engine_call(endpoint, status, seconds)


def observe_cos(operation: str, status: str, seconds: float) -> None:
    """Report one COS call, if a recorder is set."""
    if _RECORDER is not None:
        _RECORDER.observe_cos_call(operation, status, seconds)
