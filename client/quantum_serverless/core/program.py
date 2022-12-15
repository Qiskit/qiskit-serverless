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
=================================================
Provider (:mod:`quantum_serverless.core.program`)
=================================================

.. currentmodule:: quantum_serverless.core.program

Quantum serverless nested program
=================================

.. autosummary::
    :toctree: ../stubs/

    Program
"""
from typing import Optional, Dict, List
from dataclasses import dataclass


@dataclass
class Program:
    """Serverless programs.

    Args:
        entrypoint: is a script that will be executed as a job
            ex: job.py
        arguments: arguments for entrypoint script
        env_vars: env vars
        dependencies: list of python dependencies for program to execute
        working_dir: directory where entrypoint file is located
        description: description of a program
        version: version of a program
    """

    entrypoint: str
    arguments: Optional[Dict[str, str]] = None
    env_vars: Optional[Dict[str, str]] = None
    dependencies: Optional[List[str]] = None
    working_dir: Optional[str] = None
    description: Optional[str] = None
    version: Optional[str] = None
