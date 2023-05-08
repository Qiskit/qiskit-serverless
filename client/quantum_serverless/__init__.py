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
"""

from importlib_metadata import version as metadata_version, PackageNotFoundError

from .core import (
    Provider,
    run_qiskit_remote,
    distribute_task,
    get,
    put,
    get_refs_by_status,
    KuberayProvider,
    GatewayProvider,
    save_result,
)
from .quantum_serverless import QuantumServerless
from .core.program import Program
from .serializers import get_arguments

try:
    __version__ = metadata_version("quantum_serverless")
except PackageNotFoundError:  # pragma: no cover
    # package is not installed
    pass
