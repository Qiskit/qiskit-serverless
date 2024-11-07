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
================================================
Provider (:mod:`qiskit_serverless.core.client`)
================================================

.. currentmodule:: qiskit_serverless.core.client

Qiskit Serverless provider
===========================

.. autosummary::
    :toctree: ../stubs/

    LocalFunctionsStore
"""
# pylint: disable=duplicate-code
import os.path
import os
from typing import Optional, List
from qiskit_serverless.core.client import BaseClient
from qiskit_serverless.core.function import QiskitFunction, RunnableQiskitFunction
from qiskit_serverless.exception import QiskitServerlessException


class LocalFunctionsStore:
    """LocalClient."""

    def __init__(self, client: BaseClient):
        self.client = client
        self._functions: List[RunnableQiskitFunction] = []

    def upload(self, program: QiskitFunction) -> Optional[RunnableQiskitFunction]:
        """Save a function in the store"""
        if not os.path.exists(os.path.join(program.working_dir, program.entrypoint)):
            raise QiskitServerlessException(
                f"Entrypoint file [{program.entrypoint}] does not exist "
                f"in [{program.working_dir}] working directory."
            )

        pattern = {
            "title": program.title,
            "provider": program.provider,
            "entrypoint": program.entrypoint,
            "working_dir": program.working_dir,
            "env_vars": program.env_vars,
            "arguments": {},
            "dependencies": program.dependencies or [],
            "client": self.client,
        }
        runnable_function = RunnableQiskitFunction.from_json(pattern)
        self._functions.append(runnable_function)
        return runnable_function

    def functions(self) -> List[RunnableQiskitFunction]:
        """Returns list of functions."""
        return list(self._functions)

    def function(self, title: str) -> Optional[RunnableQiskitFunction]:
        """Returns a function with the provided title."""
        functions = {function.title: function for function in self.functions()}
        return functions.get(title)
