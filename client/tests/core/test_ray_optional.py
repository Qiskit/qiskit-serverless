# This code is a Qiskit project.
#
# (C) Copyright IBM 2022.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""Tests that Ray is an optional dependency of the client.

Ray is only needed for the Ray runner (``pip install qiskit-serverless[ray]``). The
client package, and the surface used by the Fleets worker, must import and run without
it; Ray-only symbols must fail with a clear, actionable error when Ray is missing.
"""

import importlib.util

import pytest

ray_installed = importlib.util.find_spec("ray") is not None
requires_no_ray = pytest.mark.skipif(ray_installed, reason="only meaningful when Ray is NOT installed")


def test_import_qiskit_serverless_without_ray():
    """Importing the package must not require Ray."""
    import qiskit_serverless  # pylint: disable=import-outside-toplevel

    assert qiskit_serverless.__version__


def test_fleets_worker_surface_imports_without_ray():
    """The Fleets worker surface must import regardless of Ray."""
    # pylint: disable=import-outside-toplevel,unused-import
    from qiskit_serverless import (
        get_arguments,
        save_result,
        get_logger,
        ServerlessClient,
        QiskitFunction,
    )


@requires_no_ray
def test_remote_raises_clear_error_without_ray():
    """``remote`` must raise a clear 'install [ray]' error, not a raw import error.

    ``remote`` is the last remaining consumer of ``_require_ray``: the other Ray-only
    helpers (``distribute_task``, ``get``, ``put``, ``get_refs_by_status``) were removed
    in favor of calling Ray directly.
    """
    # pylint: disable=import-outside-toplevel
    from qiskit_serverless.core import decorators

    with pytest.raises(ModuleNotFoundError, match=r"qiskit-serverless\[ray\]"):
        decorators.remote(num_cpus=1)
