"""Unit tests for WarnOnce."""

import threading

from core.warn_once import WarnOnce


def test_a_key_is_reported_once_until_it_is_forgotten():
    seen = WarnOnce()

    assert seen.first("job-1") is True
    assert seen.first("job-1") is False

    seen.forget("job-1")

    assert seen.first("job-1") is True


def test_the_set_is_cleared_when_it_reaches_its_limit():
    seen = WarnOnce(limit=2)
    seen.first("a")
    seen.first("b")

    assert seen.first("c") is True

    # "a" was dropped with the rest when the limit was reached, so it is reported again
    assert seen.first("a") is True
    # "c" was added after the clear, so it still counts as reported
    assert seen.first("c") is False


def test_threads_reporting_the_same_key_at_once_report_it_one_time():
    seen = WarnOnce()
    barrier = threading.Barrier(8)
    reported = []

    def report():
        barrier.wait()
        reported.append(seen.first("job-1"))

    threads = [threading.Thread(target=report) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert reported.count(True) == 1
