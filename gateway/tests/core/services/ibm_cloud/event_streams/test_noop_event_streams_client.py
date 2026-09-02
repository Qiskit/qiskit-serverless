# This code is part of a Qiskit project.
#
# (C) IBM 2026
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""Unit tests for NoOpEventStreamsClient."""

from __future__ import annotations

import uuid as uuid_module
from unittest.mock import MagicMock, patch

from core.ibm_cloud.event_streams.noop_event_streams_client import NoOpEventStreamsClient


def _make_job(filler: bool) -> MagicMock:
    job = MagicMock()
    job.id = uuid_module.uuid4()
    job.filler = filler
    return job


def test_noop_client_is_concrete():
    """All four abstract _emit_* methods are implemented, so the class can be instantiated."""
    client = NoOpEventStreamsClient()

    assert isinstance(client, NoOpEventStreamsClient)


def test_noop_client_skips_filler_jobs():
    """A filler job never reaches the private implementation; a real job does."""
    client = NoOpEventStreamsClient()

    with patch.object(client, "_emit_job_started") as mock_emit:
        client.emit_job_started(_make_job(filler=True))
        mock_emit.assert_not_called()

        real_job = _make_job(filler=False)
        client.emit_job_started(real_job)
        mock_emit.assert_called_once_with(real_job, None)
