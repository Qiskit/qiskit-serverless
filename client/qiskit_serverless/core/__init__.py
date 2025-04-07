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
    Job
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
    is_running_in_serverless

"""

from .client import BaseClient

from .clients.local_client import LocalClient
from .clients.ray_client import RayClient
from .clients.serverless_client import ServerlessClient, IBMServerlessClient

from .job import (
    Job,
    save_result,
    update_status,
    Configuration,
    is_running_in_serverless,
    is_trial,
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
