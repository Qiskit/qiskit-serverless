# This code is a Qiskit project.
#
# (C) Copyright IBM 2026.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""Tests for Job.wait_for_final_state() and Job.result(), which waits with it."""

import random
from unittest.mock import Mock, patch

import pytest

from qiskit_serverless.core.job import Job
from qiskit_serverless.core.job_event import JobEvent
from qiskit_serverless.exception import QiskitServerlessException
from qiskit_serverless.utils.errors import ErrorCodes


class FakeClock:
    """A clock that only moves when the code under test sleeps."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        """Current time in seconds."""
        return self.now

    def sleep(self, seconds):
        """Record the sleep and move the clock."""
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture(name="clock")
def fixture_clock():
    """Patch time.monotonic, time.sleep and random.uniform for the whole test."""
    clock = FakeClock()
    with (
        patch("qiskit_serverless.core.job.time.monotonic", clock.monotonic),
        patch("qiskit_serverless.core.job.time.sleep", clock.sleep),
        patch("qiskit_serverless.core.job.random.uniform", return_value=1.0),
    ):
        yield clock


def _job(*answers):
    """A job whose status checks return the given status, sub_status pairs or raise the given errors."""
    service = Mock()
    service.get_job_data.side_effect = [
        answer if isinstance(answer, Exception) else {"status": answer[0], "sub_status": answer[1]}
        for answer in answers
    ]
    return Job(job_id="job-1", job_service=service), service


def test_waits_with_the_backoff_and_returns_the_final_status(clock):
    """Checks at once, backs off, starts again on a change, and returns DONE."""
    job, _ = _job(
        ("QUEUED", None),
        ("QUEUED", None),
        ("RUNNING", None),
        ("RUNNING", None),
        ("RUNNING", None),
        ("SUCCEEDED", None),
    )

    assert job.wait_for_final_state() == "DONE"
    assert clock.sleeps == [1, 2, 1, 2, 4]


def test_a_sub_status_does_not_reset_the_backoff_but_post_processing_does(clock):
    """Only a new main status or post-processing goes back to 1 s."""
    job, _ = _job(
        ("RUNNING", None),
        ("RUNNING", None),
        ("RUNNING", "MAPPING"),
        ("RUNNING", "POST_PROCESSING"),
        ("SUCCEEDED", None),
    )

    job.wait_for_final_state()

    assert clock.sleeps == [1, 2, 4, 1]


def test_the_backoff_stops_growing_at_30_seconds(clock):
    """After 16 s every wait is 30 s."""
    job, _ = _job(*([("RUNNING", None)] * 9), ("SUCCEEDED", None))

    job.wait_for_final_state()

    assert clock.sleeps == [1, 2, 4, 8, 16, 30, 30, 30, 30]


def test_poll_interval_replaces_the_backoff_and_has_a_floor_of_one_second(clock):
    """A fixed interval is used as given, and anything under 1 s becomes 1 s."""
    job, _ = _job(("RUNNING", None), ("RUNNING", None), ("STOPPED", None))
    assert job.wait_for_final_state(poll_interval=10) == "CANCELED"
    assert clock.sleeps == [10, 10]

    clock.sleeps.clear()
    job, _ = _job(("RUNNING", None), ("FAILED", None))
    assert job.wait_for_final_state(poll_interval=0.1) == "ERROR"
    assert clock.sleeps == [1]


def test_a_timeout_raises_after_one_last_check_and_never_cancels_the_job(clock):
    """The last sleep is cut at the deadline, then one more check, then TimeoutError."""
    job, service = _job(*([("RUNNING", None)] * 5))

    with pytest.raises(TimeoutError):
        job.wait_for_final_state(timeout=5)

    assert clock.sleeps == [1, 2, 2]
    assert service.get_job_data.call_count == 4
    service.stop.assert_not_called()


def test_a_transient_error_is_retried_and_does_not_count_as_a_status_change(clock):
    """A dropped connection or a 503 is retried, and the wait ends normally."""
    job, _ = _job(
        ("RUNNING", None),
        QiskitServerlessException("down", code=ErrorCodes.CONN1001),
        QiskitServerlessException("busy", code=503),
        ("SUCCEEDED", None),
    )

    assert job.wait_for_final_state() == "DONE"
    assert clock.sleeps == [1, 2, 4]


def test_a_retry_keeps_the_pace_of_the_backoff(clock):
    """A 503 after the backoff reached 30 s waits 30 s, not 1 s, so an overloaded gateway gets fewer requests."""
    job, _ = _job(*([("RUNNING", None)] * 8), QiskitServerlessException("busy", code=503), ("SUCCEEDED", None))

    job.wait_for_final_state()

    assert clock.sleeps == [1, 2, 4, 8, 16, 30, 30, 30, 30]


def test_a_plain_500_raises_at_once(clock):
    """A gateway bug is not retried."""
    job, service = _job(("RUNNING", None), QiskitServerlessException("bug", code=500))

    with pytest.raises(QiskitServerlessException):
        job.wait_for_final_state()

    assert service.get_job_data.call_count == 2


def test_retries_stop_after_five_minutes_of_errors_in_a_row(clock):
    """With no timeout, a long outage ends the wait instead of retrying forever."""
    service = Mock()
    service.get_job_data.side_effect = QiskitServerlessException("down", code=ErrorCodes.CONN1001)
    job = Job(job_id="job-1", job_service=service)

    with pytest.raises(QiskitServerlessException):
        job.wait_for_final_state()

    assert clock.now == 300


def test_an_outage_at_the_timeout_raises_the_last_error(clock):
    """With a timeout, the retries stop at the deadline and the real error is raised."""
    service = Mock()
    service.get_job_data.side_effect = QiskitServerlessException("busy", code=503)
    job = Job(job_id="job-1", job_service=service)

    with pytest.raises(QiskitServerlessException, match="busy"):
        job.wait_for_final_state(timeout=10)

    assert clock.now == 10


def test_verbose_prints_one_line_per_status_change(clock, capsys):
    """A header, then one line each time the status changes."""
    job, _ = _job(("QUEUED", None), ("QUEUED", None), ("RUNNING", None), ("SUCCEEDED", None))

    job.wait_for_final_state(verbose=True)

    assert capsys.readouterr().out.splitlines() == [
        "Waiting for job job-1",
        "0:00:00  QUEUED",
        "0:00:03  RUNNING",
        "0:00:04  DONE",
    ]


def test_verbose_prints_a_retried_error_with_its_code(clock, capsys):
    """A retried status check shows its error code."""
    job, _ = _job(("RUNNING", None), QiskitServerlessException("busy", code=503), ("SUCCEEDED", None))

    job.wait_for_final_state(verbose=True)

    assert "0:00:01  status check failed (503), retrying" in capsys.readouterr().out.splitlines()


def test_verbose_prints_the_error_message_when_the_job_fails(clock, capsys):
    """On ERROR, verbose fetches and prints why the job failed."""
    job, service = _job(("RUNNING", None), ("FAILED", None), ("FAILED", None))
    service.events.return_value = [
        JobEvent("ERROR", "API", "SEND_ERROR", "now", {"message": "bad input", "code": 400, "exception": "E"})
    ]

    assert job.wait_for_final_state(verbose=True) == "ERROR"

    assert "| Message: bad input" in capsys.readouterr().out


def test_a_failed_job_without_verbose_makes_no_extra_request(clock, capsys):
    """The error message is fetched only in verbose mode, so the default stays one request per check."""
    job, service = _job(("FAILED", None))

    assert job.wait_for_final_state() == "ERROR"

    service.events.assert_not_called()
    assert capsys.readouterr().out == ""


def test_a_failure_getting_the_error_message_still_returns_error(clock, capsys):
    """If the error message cannot be fetched, verbose says so and the wait still returns ERROR."""
    job, service = _job(("FAILED", None))
    service.events.side_effect = QiskitServerlessException("down", code=ErrorCodes.CONN1001)

    assert job.wait_for_final_state(verbose=True) == "ERROR"

    assert capsys.readouterr().out.splitlines()[-1] == "Something went wrong getting the error message."


def test_a_final_status_is_fetched_only_once(clock):
    """After a final status, status() and the methods that call it make no more status requests."""
    job, service = _job(("FAILED", None))
    service.events.return_value = []
    service.result.return_value = "it failed"

    assert job.wait_for_final_state() == "ERROR"
    with pytest.raises(QiskitServerlessException, match="it failed"):
        job.result(wait=True)

    assert service.get_job_data.call_count == 1


def test_result_waits_with_wait_for_final_state(clock):
    """result() waits with the backoff, then reads the results once."""
    job, service = _job(("RUNNING", None), ("RUNNING", None), ("SUCCEEDED", None))
    service.result.return_value = '{"answer": 42}'

    assert job.result() == {"answer": 42}
    assert clock.sleeps == [1, 2]
    service.result.assert_called_once_with("job-1")


def test_result_cadence_is_a_fixed_poll_interval(clock):
    """A cadence keeps a fixed interval, as before."""
    job, service = _job(("RUNNING", None), ("SUCCEEDED", None))
    service.result.return_value = "{}"

    job.result(cadence=5)

    assert clock.sleeps == [5]


def test_result_timeout_raises_and_reads_no_results(clock):
    """A timeout raises TimeoutError before any result request."""
    job, service = _job(*([("RUNNING", None)] * 5))

    with pytest.raises(TimeoutError):
        job.result(timeout=3)

    service.result.assert_not_called()


def test_result_maxwait_is_deprecated_and_waits_maxwait_times_cadence(clock):
    """maxwait warns, waits maxwait times cadence seconds, and still reads the results."""
    job, service = _job(*([("RUNNING", None)] * 5))
    service.result.return_value = "{}"

    with pytest.warns(DeprecationWarning, match="maxwait"):
        job.result(cadence=1, maxwait=3)

    assert clock.sleeps == [1, 1, 1]
    service.result.assert_called_once_with("job-1")


def test_result_maxwait_with_timeout_raises():
    """maxwait and timeout cannot be used together."""
    job, _ = _job()

    with pytest.warns(DeprecationWarning), pytest.raises(ValueError):
        job.result(maxwait=3, timeout=10)


def test_result_retries_a_503_while_waiting(clock):
    """A 503 during the wait is retried, and the results are still returned."""
    job, service = _job(("RUNNING", None), QiskitServerlessException("busy", code=503), ("SUCCEEDED", None))
    service.result.return_value = "{}"

    assert job.result() == {}


def test_the_jitter_only_shortens_a_wait(clock):
    """The jitter takes up to 10% off each wait, so no wait is longer than 30 s."""
    job, _ = _job(*([("RUNNING", None)] * 6), ("SUCCEEDED", None))

    with patch("qiskit_serverless.core.job.random.uniform", wraps=random.uniform) as uniform:
        job.wait_for_final_state()

    uniform.assert_called_with(0.9, 1)
    assert max(clock.sleeps) <= 30
