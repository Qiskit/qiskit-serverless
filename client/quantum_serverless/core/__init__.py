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
Core module (:mod:`quantum_serverless.core`)
============================================

.. currentmodule:: quantum_serverless.core

Quantum serverless core module classes and functions
====================================================

Core abstractions
-----------------

.. autosummary::
    :toctree: ../stubs/

    Provider
    ServerlessProvider
    IBMServerlessProvider
    BaseProvider
    RayProvider
    ComputeResource
    Job
    GatewayJobClient
    BaseJobClient
    RayJobClient
    save_result
    Program
    ProgramStorage
    ProgramRepository
    download_and_unpack_artifact
    Target
    CircuitMeta
    fetch_execution_meta
    distribute_task
    distribute_program
    get
    put
    get_refs_by_status

"""

from .provider import (
    BaseProvider,
    ComputeResource,
    Provider,
    ServerlessProvider,
    IBMServerlessProvider,
    RayProvider,
)
from .job import BaseJobClient, RayJobClient, GatewayJobClient, Job, save_result
from .program import (
    Program,
    ProgramStorage,
    ProgramRepository,
    download_and_unpack_artifact,
)
from .decorators import (
    remote,
    get,
    put,
    get_refs_by_status,
    fetch_execution_meta,
    distribute_task,
    distribute_program,
    Target,
    CircuitMeta,
)
