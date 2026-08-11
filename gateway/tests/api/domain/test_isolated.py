import os

import pytest

from api.domain.isolated import IsolationError, _collect, run_isolated  # pylint: disable=protected-access


def test_returns_the_value_the_work_produced():
    assert run_isolated(lambda: {"ok": True, "n": 3}) == {"ok": True, "n": 3}


def test_cpu_limit_kills_work_that_will_not_stop():
    import re
    import time

    pattern = re.compile("^(a+)+$")  # exponential, and does not release control
    start = time.monotonic()
    with pytest.raises(IsolationError) as caught:
        run_isolated(lambda: pattern.search("a" * 40 + "!") is None, cpu_seconds=1)
    elapsed = time.monotonic() - start
    assert "CPU time" in caught.value.reason
    # Comfortably under the 5.0s default wall_seconds, so the wall-clock fallback path (which
    # reports a different reason) cannot satisfy this test by accident.
    assert elapsed < 3.0


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
