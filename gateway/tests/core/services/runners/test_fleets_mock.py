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

"""Tests for the Code Engine mock used by the local fleets integration stack.

The module reads its MinIO settings from the environment at import time, because it is only
imported when ``FLEETS_MOCK_ENABLED=1`` where they are always set. Tests therefore import it
under a patched environment rather than at module scope.
"""

import importlib
import os
from unittest.mock import MagicMock, patch

from core.ibm_cloud.code_engine.fleets.cos import queue_prefix

_MOCK_ENV = {
    "MINIO_ENDPOINT": "http://minio:9000",
    "MINIO_ACCESS_KEY": "minioadmin",
    "MINIO_SECRET_KEY": "minioadmin",
}


def _load_fleets_mock():
    """Import the mock module with the environment it expects at import time.

    Two things to know before adding a second caller. Once the module is in ``sys.modules`` this
    returns the cached one, with the first caller's environment already baked in. And if anything
    ever imports it earlier without ``MINIO_*`` set, the reads at import raise ``KeyError`` during
    collection, which no ``patch.dict`` here can rescue.
    """
    with patch.dict(os.environ, _MOCK_ENV):
        return importlib.import_module("core.services.runners.fleets_mock")


def test_mock_cancel_job_reports_the_cancel_as_delivered():
    """The mock's cancel must return True, matching the real ``cancel_job``.

    Nothing else in the suite catches this. ``install_mocks()`` replaces ``cancel_job`` wholesale,
    both scheduler callers ignore what ``stop()`` returns, and the stop endpoint writes ``STOPPED``
    before it calls the runner. So a falsy return would surface only as the local stack telling a
    user their job was "already stopping or no longer running" after a cancel that worked.
    """
    fleets_mock = _load_fleets_mock()

    handler = MagicMock()
    handler.project_id = "test-project-id"
    s3 = MagicMock()
    # No cancel key yet. This also covers the "COS blew up" case, which takes the same branch on
    # purpose: a failed existence probe must never stop us writing the cancel.
    s3.head_object.side_effect = Exception("NoSuchKey")

    with (
        patch.object(fleets_mock, "_get_mock_s3", return_value=s3),
        patch.object(fleets_mock, "_task_store_bucket", return_value="task-store-bucket"),
    ):
        result = fleets_mock._mock_cancel_job(handler, "fleet-123")  # pylint: disable=protected-access

    assert result is True
    # It still has to write the key the worker and status() read, or the stack stops converging.
    prefix = queue_prefix("test-project-id", "fleet-123")
    s3.put_object.assert_called_once_with(
        Bucket="task-store-bucket",
        Key=f"{prefix}canceled/0/fleet-123-0/canceled",
        Body=b"",
    )


def test_mock_cancel_job_reports_nothing_to_cancel_when_one_is_already_in_flight():
    """A second cancel returns False, the way the real ``cancel_job`` answers a 409.

    This is the only way the local stack can reach ``stop()``'s False branch, since
    ``install_mocks`` replaces ``cancel_job`` wholesale and the handler's own 404/409 mapping never
    runs there.
    """
    fleets_mock = _load_fleets_mock()

    handler = MagicMock()
    handler.project_id = "test-project-id"
    s3 = MagicMock()  # head_object succeeds, so a cancel key is already present

    with (
        patch.object(fleets_mock, "_get_mock_s3", return_value=s3),
        patch.object(fleets_mock, "_task_store_bucket", return_value="task-store-bucket"),
    ):
        result = fleets_mock._mock_cancel_job(handler, "fleet-123")  # pylint: disable=protected-access

    assert result is False
    s3.put_object.assert_not_called()
