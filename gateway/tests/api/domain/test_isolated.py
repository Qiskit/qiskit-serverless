import os
import signal

import pytest

from api.domain import isolated
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


def test_the_wall_clock_deadline_scales_with_the_cpu_budget(monkeypatch):
    """The CPU budget is configurable, and the deadline has to keep the same tolerance to a slowed
    down child at every budget, not just at the default one. A child getting a fraction f of a core
    spends its budget in budget/f wall seconds, so a deadline that added a constant would tolerate
    less and less as the budget grew: four seconds on top of one tolerates a 5x slowdown, four on top
    of five only 1.8x, which would leave a schema legitimately needing 3 CPU seconds refused at a
    budget of 5, the case raising the budget exists to allow.

    Asserted as the two properties that matter, not as the literal number: the deadline stays above
    RLIMIT_CPU's hard cap (the budget plus one second), and it still tolerates the same slowdown at
    the highest budget arguments_schema allows as it does at the default one.

    The spy runs in the parent, which is the only side that calls _collect, so unlike an earlier test
    in this feature it does observe the real call rather than a copy lost across the fork.
    """
    real_collect = isolated._collect  # pylint: disable=protected-access
    seen = {}

    def spy(pid, read_fd, wall_seconds, cpu_seconds):
        seen[cpu_seconds] = wall_seconds
        return real_collect(pid, read_fd, wall_seconds, cpu_seconds)

    monkeypatch.setattr(isolated, "_collect", spy)

    for budget in (1, 5):
        assert run_isolated(lambda: {"ok": True}, cpu_seconds=budget) == {"ok": True}
        assert seen[budget] > budget + 1

    assert seen[5] / 5 == seen[1] / 1


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
    "verified by running this child under both. On Linux it is killed with SIGKILL at 2.00s of CPU "
    "time, matching the hard limit; on macOS the same child was never signalled at all and kept "
    "running, so here it would stop only at the wall-clock deadline and report that instead.",
)
def test_cpu_hard_limit_kill_is_still_reported_as_a_cpu_overrun():
    """When a child ignores SIGXCPU, the RLIMIT_CPU hard limit kills it with SIGKILL a second
    later, having actually spent the CPU budget: that SIGKILL must still read as a CPU overrun.

    The child loops until it is killed, rather than for a fixed stretch of wall clock, and the
    deadline is passed in generously rather than derived. Both remove a race this test used to have
    with the wall clock: the hard cap needs two CPU seconds, which on a quarter of a core is eight
    seconds of wall clock, so a child looping for five wall seconds under that throttle was never
    hard-capped at all and the deadline reported the failure instead. 60 seconds leaves the hard cap
    30x the room it needs, while still ending the test rather than hanging if it never fires.
    """

    def work():
        signal.signal(signal.SIGXCPU, signal.SIG_IGN)
        while True:
            pass

    with pytest.raises(IsolationError) as caught:
        run_isolated(work, cpu_seconds=1, wall_seconds=60.0)
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


def test_a_failure_before_the_read_still_kills_and_reaps_the_child(monkeypatch):
    """Nothing between the fork and os.wait4 may let the child outlive the call that created it.

    selectors.DefaultSelector allocates a descriptor of its own (epoll_create1), so it fails under
    exactly the descriptor pressure the os.fork handler above was written for. Left unhandled, that
    OSError escaped run_isolated as the 500 this module exists to prevent, and left the child both
    unkilled, so it ran on to its CPU limit inside a worker that had already answered, and unreaped,
    so it then sat as a zombie for the rest of that worker's life.

    The reap is asserted through waitpid rather than by inspecting the process table: a child this
    process still owns answers (0, 0) while it runs and (pid, status) once it is a zombie, so only a
    reaped one raises ChildProcessError.
    """
    real_fork = os.fork
    forked = {}

    def spy_fork():
        pid = real_fork()
        if pid:
            forked["pid"] = pid
        return pid

    def unavailable(*_args, **_kwargs):
        raise OSError(24, "Too many open files")

    monkeypatch.setattr(os, "fork", spy_fork)
    monkeypatch.setattr(isolated.selectors, "DefaultSelector", unavailable)

    with pytest.raises(IsolationError) as caught:
        run_isolated(lambda: {"ok": True})
    assert "Too many open files" in caught.value.reason

    with pytest.raises(ChildProcessError):
        os.waitpid(forked["pid"], os.WNOHANG)


@pytest.mark.django_db
def test_forking_does_not_break_the_parents_database_connection():
    from django.db import connection

    assert run_isolated(lambda: {"ok": True}) == {"ok": True}
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        assert cursor.fetchone() == (1,)
