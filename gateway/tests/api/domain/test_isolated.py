import os
import signal
import time

import pytest

from api.domain.isolated import IsolationError, _collect, run_isolated  # pylint: disable=protected-access


def test_returns_the_value_the_work_produced():
    assert run_isolated(lambda: {"ok": True, "n": 3}) == {"ok": True, "n": 3}


def test_cpu_limit_kills_work_that_will_not_stop():
    import re

    pattern = re.compile("^(a+)+$")  # exponential, and does not release control
    with pytest.raises(IsolationError) as caught:
        run_isolated(lambda: pattern.search("a" * 40 + "!") is None, cpu_seconds=1)
    # Assert the cause, not elapsed wall-clock time: the wall-clock fallback path reports a
    # different reason ("wall-clock time" instead of "CPU time"), so this alone proves RLIMIT_CPU
    # is what stopped the work, regardless of how long that took on a loaded or throttled runner.
    assert "CPU time" in caught.value.reason


def test_work_returning_something_unencodable_is_reported_not_hung():
    with pytest.raises(IsolationError) as caught:
        run_isolated(lambda: object())
    assert "JSON" in caught.value.reason


def test_a_truncated_write_is_reported_not_propagated():
    """A child killed mid-write (wall clock SIGKILL, or a hard memory limit) can leave a partial
    write in the pipe: valid bytes so far, but not a complete JSON document. json.loads raising
    JSONDecodeError on that must come back as IsolationError, not escape uncaught."""
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        os.write(write_fd, b'{"result": tr')  # truncated on purpose, not valid JSON
        os.close(write_fd)
        os._exit(0)  # pylint: disable=protected-access

    os.close(write_fd)
    try:
        with pytest.raises(IsolationError) as caught:
            _collect(pid, read_fd, wall_seconds=2.0, cpu_seconds=1)
        assert "answer" in caught.value.reason
    finally:
        os.close(read_fd)


def test_work_that_raises_is_reported_not_propagated():
    def work():
        raise ValueError("boom")

    with pytest.raises(IsolationError) as caught:
        run_isolated(work)
    assert "ValueError" in caught.value.reason


def test_a_fork_that_cannot_be_created_is_reported_not_propagated(monkeypatch):
    """A failing os.fork (EAGAIN under process-table pressure, for example) used to escape
    run_isolated as a raw OSError, and leaked both ends of the pipe it had just opened: five
    attempts drove this process's open descriptors from 4 to 14."""

    def _raise(*_args, **_kwargs):
        raise BlockingIOError(11, "Resource temporarily unavailable")

    monkeypatch.setattr(os, "fork", _raise)

    fd_count_before = len(os.listdir("/dev/fd")) if os.path.isdir("/dev/fd") else None
    for _ in range(5):
        with pytest.raises(IsolationError) as caught:
            run_isolated(lambda: {"ok": True})
        assert "could not be started" in caught.value.reason

    if fd_count_before is not None:
        assert len(os.listdir("/dev/fd")) == fd_count_before


def test_an_external_kill_is_not_reported_as_a_cpu_overrun():
    """An OOM-killed child, or any external SIGKILL unrelated to the CPU limit, must not read as
    a CPU overrun: only the CPU limit's own hard-cap SIGKILL, arriving after the child actually
    spent close to its CPU budget, means that."""

    def work():
        os.kill(os.getpid(), signal.SIGKILL)  # simulates an external kill, e.g. the OOM killer

    with pytest.raises(IsolationError) as caught:
        run_isolated(work, cpu_seconds=5)
    assert "CPU time" not in caught.value.reason
    assert "memory" in caught.value.reason


@pytest.mark.skipif(
    not os.path.exists("/proc/self/status"),
    reason="RLIMIT_CPU's hard limit is not enforced on macOS once the process ignores SIGXCPU: "
    "verified by running this exact child under both. On Linux it is killed with SIGKILL at "
    "2.00s of CPU time, matching the hard limit; on macOS it ran the full 5s loop to completion, "
    "used ~5s of CPU, and was never signalled at all.",
)
def test_cpu_hard_limit_kill_is_still_reported_as_a_cpu_overrun():
    """When a child ignores SIGXCPU, the RLIMIT_CPU hard limit kills it with SIGKILL a second
    later, having actually spent the CPU budget: that SIGKILL must still read as a CPU overrun."""

    def work():
        signal.signal(signal.SIGXCPU, signal.SIG_IGN)
        end = time.monotonic() + 5
        while time.monotonic() < end:
            pass

    with pytest.raises(IsolationError) as caught:
        run_isolated(work, cpu_seconds=1, wall_seconds=5.0)
    assert "CPU time" in caught.value.reason


@pytest.mark.skipif(
    not os.path.exists("/proc/self/status"),
    reason="RLIMIT_AS does not bound anything on macOS: base address space is 425 GB there against "
    "25 MB on Linux, so any margin is lost in the noise. Verified by running the attack under a "
    "256 MB margin on both: killed on Linux, completed on macOS.",
)
def test_memory_limit_stops_an_oversized_allocation():
    with pytest.raises(IsolationError) as caught:
        run_isolated(lambda: len(bytearray(400 * (1 << 20))), memory_mb=64)
    assert "memory" in caught.value.reason


@pytest.mark.django_db
def test_forking_does_not_break_the_parents_database_connection():
    from django.db import connection

    assert run_isolated(lambda: {"ok": True}) == {"ok": True}
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        assert cursor.fetchone() == (1,)
