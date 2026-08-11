import os

import pytest

from api.domain.isolated import IsolationError, run_isolated


def test_returns_the_value_the_work_produced():
    assert run_isolated(lambda: {"ok": True, "n": 3}) == {"ok": True, "n": 3}


def test_cpu_limit_kills_work_that_will_not_stop():
    import re

    pattern = re.compile("^(a+)+$")  # exponential, and does not release control
    with pytest.raises(IsolationError) as caught:
        run_isolated(lambda: pattern.search("a" * 40 + "!") is None, cpu_seconds=1)
    assert "CPU time" in caught.value.reason


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
