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
import json
import logging
import os
from abc import ABC
from typing import Optional, Dict, List
from dataclasses import dataclass, asdict

import requests

from quantum_serverless.core.constrants import REPO_PREFIX_KEY, REPO_HOST_KEY, REPO_PORT_KEY


@dataclass
class Program:  # pylint: disable=too-many-instance-attributes
    """Serverless programs.

    Args:
        title: program name
        entrypoint: is a script that will be executed as a job
            ex: job.py
        arguments: arguments for entrypoint script
        env_vars: env vars
        dependencies: list of python dependencies for program to execute
        working_dir: directory where entrypoint file is located
        description: description of a program
        version: version of a program
    """

    title: str
    entrypoint: str
    working_dir: str = "./"
    arguments: Optional[Dict[str, str]] = None
    env_vars: Optional[Dict[str, str]] = None
    dependencies: Optional[List[str]] = None
    description: Optional[str] = None
    version: Optional[str] = None
    tags: Optional[List[str]] = None


class ProgramStorage(ABC):
    """Base program backend to save and load programs from."""

    def save_program(self, program: Program) -> bool:
        """Save program in specified backend.

        Args:
            program: program

        Returns:
            success state
        """
        raise NotImplementedError

    def get_programs(self, **kwargs) -> List[str]:
        """Returns list of available programs to get.

        Args:
            kwargs: filtering criteria

        Returns:
            List of names of programs
        """
        raise NotImplementedError

    def get_program(self, program_id: str, **kwargs) -> Optional[Program]:
        """Returns program by name of other query criterieas.

        Args:
            program_id: id of program
            **kwargs: other args

        Returns:
            Program
        """
        raise NotImplementedError


class ProgramRepository(ProgramStorage):
    """ProgramRepository."""
    def __init__(self,
                 host: Optional[str] = None,
                 port: Optional[int] = None,
                 token: Optional[str] = None
                 ):
        """Program repository implementation.

        Args:
            host: host of backend
            port: port of backend
            token: authentication token
        """
        self._host = host or os.environ.get(REPO_HOST_KEY, "localhost")
        self._port = port or os.environ.get(REPO_PORT_KEY, 80)
        self._token = token
        self._base_url = f"{os.environ.get(REPO_PREFIX_KEY, 'http')}://{self._host}:{self._port}/api/v1/nested-programs/"

    def save_program(self, program: Program) -> bool:
        raise NotImplementedError("Not implemented yet.")

    def get_programs(self, **kwargs) -> List[str]:
        result = []
        response = requests.get(url=self._base_url, params=kwargs)
        if response.ok:
            response_data = json.loads(response.text)
            result = [
                entry.get("title") for entry in
                response_data.get("results", [])
            ]
        return result

    def get_program(self, program_id: str, **kwargs) -> Optional[Program]:
        result = None
        response = requests.get(url=f"{self._base_url}/{program_id}")
        if response.ok:
            try:
                response_data = json.loads(response.text)
                result = Program(**response_data)
            except Exception as e:
                logging.warning(f"Something went wrong during program request: {e}")
        return result