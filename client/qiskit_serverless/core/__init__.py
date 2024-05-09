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
============================================
Core module (:mod:`qiskit_serverless.core`)
============================================

.. currentmodule:: qiskit_serverless.core

Qiskit Serverless core module classes and functions
====================================================

Core abstractions
-----------------

.. autosummary::
    :toctree: ../stubs/

    ServerlessClient
    IBMServerlessClient
    BaseClient
    RayClient
    LocalClient
    ComputeResource
    Job
    GatewayJobClient
    BaseJobClient
    RayJobClient
    save_result
    QiskitPattern
    QiskitFunction
    Target
    CircuitMeta
    fetch_execution_meta
    distribute_task
    distribute_program
    distribute_qiskit_function
    get
    put
    get_refs_by_status

"""

from .client import (
    BaseProvider,
    BaseClient,
    ComputeResource,
    ServerlessProvider,
    ServerlessClient,
    IBMServerlessProvider,
    IBMServerlessClient,
    LocalProvider,
    LocalClient,
    RayProvider,
    RayClient,
)

from .job import (
    BaseJobClient,
    RayJobClient,
    GatewayJobClient,
    LocalJobClient,
    Job,
    save_result,
    Configuration,
)
from .function import QiskitPattern, QiskitFunction
from .decorators import (
    remote,
    get,
    put,
    get_refs_by_status,
    fetch_execution_meta,
    distribute_task,
    distribute_qiskit_function,
    distribute_program,
    Target,
    CircuitMeta,
)
