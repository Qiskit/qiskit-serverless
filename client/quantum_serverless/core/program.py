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

Quantum serverless program
==========================

.. autosummary::
    :toctree: ../stubs/

    Program
"""
import dataclasses
import json
import logging
import os
import tarfile
from abc import ABC
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, List, Any

import requests

from quantum_serverless.core.constants import (
    REPO_HOST_KEY,
    REPO_PORT_KEY,
)
from quantum_serverless.exception import QuantumServerlessException


@dataclass
class Program:  # pylint: disable=too-many-instance-attributes
    """Serverless Program.

    Args:
        title: program name
        entrypoint: is a script that will be executed as a job
            ex: job.py
        env_vars: env vars
        dependencies: list of python dependencies to execute a program
        working_dir: directory where entrypoint file is located (max size 50MB)
        description: description of a program
        version: version of a program
    """

    title: str
    entrypoint: Optional[str] = None
    working_dir: Optional[str] = "./"
    env_vars: Optional[Dict[str, str]] = None
    dependencies: Optional[List[str]] = None
    description: Optional[str] = None
    version: Optional[str] = None
    tags: Optional[List[str]] = None
    raw_data: Optional[Dict[str, Any]] = None

    @classmethod
    def from_json(cls, data: Dict[str, Any]):
        """Reconstructs Program from dictionary."""
        field_names = set(f.name for f in dataclasses.fields(Program))
        return Program(**{k: v for k, v in data.items() if k in field_names})

    def __str__(self):
        return f"Program({self.title})"

    def __repr__(self):
        return self.__str__()


class ProgramStorage(ABC):
    """Base program backend to save and load programs from."""

    def save_program(self, program: Program) -> bool:
        """Save program in specified backend.

        Args:
            program: program object

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

    def get_program(self, title: str, **kwargs) -> Optional[Program]:
        """Returns program by name and other query criteria.

        Args:
            title: title of the program
            **kwargs: other args

        Returns:
            Program
        """
        raise NotImplementedError


class ProgramRepository(ProgramStorage):
    """ProgramRepository."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        token: Optional[str] = None,
        folder: Optional[str] = None,
    ):
        """Program repository implementation.

        Args:
            host: host of backend
            port: port of backend
            token: authentication token
            folder: path to directory where title files will be stored
        """
        self.folder = folder or os.path.dirname(os.path.abspath(__file__))
        self._host = host or os.environ.get(REPO_HOST_KEY, "http://localhost")
        self._port = port or os.environ.get(REPO_PORT_KEY, 80)
        self._token = token
        self._base_url = f"{self._host}:{self._port}/api/v1/programs/"

    def save_program(self, program: Program) -> bool:
        raise NotImplementedError("Not implemented yet.")

    def get_programs(self, **kwargs) -> List[str]:
        result = []
        response = requests.get(url=self._base_url, params=kwargs, timeout=10)
        if response.ok:
            response_data = json.loads(response.text)
            result = [entry.get("title") for entry in response_data.get("results", [])]
        return result

    def get_program(self, title: str, **kwargs) -> Optional[Program]:
        result = None
        response = requests.get(
            url=f"{self._base_url}",
            params={"title": title},
            allow_redirects=True,
            timeout=10,
        )
        if response.ok:
            response_data = json.loads(response.text)
            results = response_data.get("results", [])
            if len(results) > 0:
                artifact = results[0].get("artifact")
                result = Program.from_json(results[0])
                result.working_dir = download_and_unpack_artifact(
                    artifact_url=artifact, program=result, folder=self.folder
                )
            else:
                logging.warning("No entries were found for your request.")
        return result


def download_and_unpack_artifact(
    artifact_url: str,
    program: Program,
    folder: str,
    headers: Optional[Dict[str, Any]] = None,
) -> str:
    """Downloads and extract artifact files into destination folder.

    Args:
        artifact_url: url to get artifact from
        program: program object artifact belongs to
        folder: root of programs folder a.k.a unpack destination
        headers: optional headers needed for download requests

    Returns:
        workdir for program
    """
    program_folder_path = os.path.join(folder, program.title)
    artifact_file_name = "artifact"
    tarfile_path = os.path.join(program_folder_path, artifact_file_name)

    # check if program path already exist on the disc
    if os.path.exists(program_folder_path):
        logging.warning("Program folder already exist. Will be overwritten.")

    # download file
    response = requests.get(url=artifact_url, stream=True, headers=headers, timeout=100)
    if not response.ok:
        raise QuantumServerlessException(
            f"Error during fetch of [{artifact_url}] file."
        )

    Path(program_folder_path).mkdir(parents=True, exist_ok=True)

    with open(tarfile_path, "wb") as file:
        for data in response.iter_content():
            file.write(data)

    # unpack tarfile
    with tarfile.open(tarfile_path, "r") as file_obj:
        file_obj.extractall(program_folder_path)

    # delete artifact
    if os.path.exists(tarfile_path):
        os.remove(tarfile_path)
    return program_folder_path
