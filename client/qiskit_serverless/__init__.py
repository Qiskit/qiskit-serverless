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

"""
.. currentmodule:: qiskit_serverless

.. autosummary::
    :toctree: ../stubs/

    QiskitServerlessException
"""
# pylint: disable=W0404
from importlib_metadata import version as metadata_version, PackageNotFoundError

from .core import (
    BaseProvider,
    BaseClient,
    distribute_task,
    distribute_qiskit_function,
    get,
    put,
    get_refs_by_status,
    ServerlessProvider,
    ServerlessClient,
    IBMServerlessProvider,
    IBMServerlessClient,
    RayProvider,
    RayClient,
    LocalProvider,
    LocalClient,
    save_result,
    Configuration,
)
from .exception import QiskitServerlessException
from .core.function import QiskitPattern, QiskitFunction
from .serializers import get_arguments
from .utils import ServerlessRuntimeService

try:
    __version__ = metadata_version("qiskit_serverless")
except PackageNotFoundError:  # pragma: no cover
    # package is not installed
    pass
