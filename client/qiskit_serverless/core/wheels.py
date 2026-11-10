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

"""
Runtime helper for installing user-uploaded wheels
===================================================

Install wheels that were uploaded to a function's file area (see
``client.add_wheels()``) from the function's entrypoint, so they are importable
during execution.
"""

import os
import site
import subprocess
import sys
from typing import Optional

# Where a function's uploaded user files are mounted inside the runtime container.
FUNCTION_USER_DATA = "/function_user_data"

# Sub-directory of the function's file area that ``client.add_wheels()`` uploads into, and that
# this helper installs from. Keeping wheels in their own directory keeps them separate from any
# other files a function uploads. The client passes this name to the files API as the sub-path.
WHEELS_SUBDIR = "wheels"

# Default directory to install wheels from: the ``wheels`` sub-directory of the uploaded user data.
DEFAULT_WHEELHOUSE = f"{FUNCTION_USER_DATA}/{WHEELS_SUBDIR}"

# Optional environment override, in case the mount location is relocated by ops.
ENV_WHEELHOUSE = "QISKIT_FUNCTIONS_WHEELHOUSE"

# Where installed wheels are placed and added to the import path.
DEFAULT_TARGET = "/tmp/site"


def install_uploaded_wheels(
    wheelhouse: Optional[str] = None,
    target: str = DEFAULT_TARGET,
) -> str:
    """Install wheels uploaded to this function and make them importable.

    Call this at the top of your entrypoint, before importing the uploaded packages::

        from qiskit_serverless import install_uploaded_wheels
        install_uploaded_wheels()
        import mypkg  # now importable

    It runs ``pip install --no-index --no-deps --find-links <wheelhouse> --target <target>``
    over every wheel in ``wheelhouse`` and prepends ``target`` to ``sys.path``. ``--no-index``
    keeps the install fully offline, and ``--no-deps`` is required: otherwise ``--no-index`` makes
    pip try to satisfy dependencies that are already baked into the image (numpy, qiskit, ...) from
    the wheelhouse and fail. Build your wheels with everything they need, or rely on what the image
    already ships (see ``client.dependencies_versions()``).

    Note: wheels are installed on every execution. If no wheels are present this is a no-op.

    Args:
        wheelhouse: directory to install wheels from. Defaults to the ``QISKIT_FUNCTIONS_WHEELHOUSE``
            environment variable if set, otherwise ``/function_user_data`` (where uploads land).
        target: directory to install into and prepend to ``sys.path``. Defaults to ``/tmp/site``.

    Returns:
        The ``target`` directory the wheels were installed into.
    """
    wheelhouse = wheelhouse or os.environ.get(ENV_WHEELHOUSE) or DEFAULT_WHEELHOUSE

    wheels = []
    if os.path.isdir(wheelhouse):
        wheels = [name for name in os.listdir(wheelhouse) if name.endswith(".whl")]

    if not wheels:
        # Nothing to install; still ensure target is importable if it already exists.
        _prepend_to_path(target)
        return target

    os.makedirs(target, exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            "--find-links",
            wheelhouse,
            "--target",
            target,
            *[os.path.join(wheelhouse, name) for name in wheels],
        ],
        check=True,
    )

    _prepend_to_path(target)
    return target


def _prepend_to_path(target: str) -> None:
    """Make packages installed under ``target`` importable in this process."""
    if os.path.isdir(target) and target not in sys.path:
        sys.path.insert(0, target)
        # Process .pth files and namespace packages the install may have created.
        site.addsitedir(target)
