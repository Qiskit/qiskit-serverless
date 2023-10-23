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
.. currentmodule:: quantum_serverless

.. autosummary::
    :toctree: ../stubs/

    QuantumServerless
    QuantumServerlessException
    get_auto_discovered_provider
"""

from importlib_metadata import version as metadata_version, PackageNotFoundError

from .core import (
    BaseProvider,
    distribute_task,
    distribute_program,
    get,
    put,
    get_refs_by_status,
    Provider,
    ServerlessProvider,
    IBMServerlessProvider,
    RayProvider,
    save_result,
)
from .quantum_serverless import (
    QuantumServerless,
    get_auto_discovered_provider,
    QuantumServerlessException,
)
from .core.program import Program
from .serializers import get_arguments

try:
    __version__ = metadata_version("quantum_serverless")
except PackageNotFoundError:  # pragma: no cover
    # package is not installed
    pass
