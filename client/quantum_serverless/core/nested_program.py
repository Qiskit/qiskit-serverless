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
========================================================
Provider (:mod:`quantum_serverless.core.nested_program`)
========================================================

.. currentmodule:: quantum_serverless.core.nested_program

Quantum serverless nested nested_program
========================================

.. autosummary::
    :toctree: ../stubs/

    NestedProgram
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
from quantum_serverless.utils.json import is_jsonable


@dataclass
class NestedProgram:  # pylint: disable=too-many-instance-attributes
    """Serverless nested_programs.

    Args:
        title: nested_program name
        entrypoint: is a script that will be executed as a job
            ex: job.py
        arguments: arguments for entrypoint script
        env_vars: env vars
        dependencies: list of python dependencies for nested_program to execute
        working_dir: directory where entrypoint file is located
        description: description of a nested_program
        version: version of a nested_program
    """

    title: str
    entrypoint: str
    working_dir: str = "./"
    arguments: Optional[Dict[str, Any]] = None
    env_vars: Optional[Dict[str, str]] = None
    dependencies: Optional[List[str]] = None
    description: Optional[str] = None
    version: Optional[str] = None
    tags: Optional[List[str]] = None

    @classmethod
    def from_json(cls, data: Dict[str, Any]):
        """Reconstructs NestedProgram from dictionary."""
        field_names = set(f.name for f in dataclasses.fields(NestedProgram))
        return NestedProgram(**{k: v for k, v in data.items() if k in field_names})

    def __post_init__(self):
        if self.arguments is not None and not is_jsonable(self.arguments):
            raise QuantumServerlessException(
                "Arguments provided are not json serializable."
            )


class NestedProgramStorage(ABC):
    """Base nested_program backend to save and load nested_programs from."""

    def save_nested_program(self, nested_program: NestedProgram) -> bool:
        """Save nested_program in specified backend.

        Args:
            nested_program: nested_program

        Returns:
            success state
        """
        raise NotImplementedError

    def get_nested_programs(self, **kwargs) -> List[str]:
        """Returns list of available nested_programs to get.

        Args:
            kwargs: filtering criteria

        Returns:
            List of names of nested_programs
        """
        raise NotImplementedError

    def get_nested_program(self, title: str, **kwargs) -> Optional[NestedProgram]:
        """Returns nested_program by name of other query criteria.

        Args:
            title: title of the nested_program
            **kwargs: other args

        Returns:
            NestedProgram
        """
        raise NotImplementedError


class NestedProgramRepository(NestedProgramStorage):
    """NestedProgramRepository."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        token: Optional[str] = None,
        folder: Optional[str] = None,
    ):
        """NestedProgram repository implementation.

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
        self._base_url = f"{self._host}:{self._port}/v1/api/nested-nested_programs/"

    def save_nested_program(self, nested_program: NestedProgram) -> bool:
        raise NotImplementedError("Not implemented yet.")

    def get_nested_programs(self, **kwargs) -> List[str]:
        result = []
        response = requests.get(url=self._base_url, params=kwargs, timeout=10)
        if response.ok:
            response_data = json.loads(response.text)
            result = [entry.get("title") for entry in response_data.get("results", [])]
        return result

    def get_nested_program(self, title: str, **kwargs) -> Optional[NestedProgram]:
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
                result = NestedProgram.from_json(results[0])
                result.working_dir = download_and_unpack_artifact(
                    artifact_url=artifact, nested_program=result, folder=self.folder
                )
            else:
                logging.warning("No entries were found for your request.")
        return result


def download_and_unpack_artifact(
    artifact_url: str,
    nested_program: NestedProgram,
    folder: str,
    headers: Optional[Dict[str, Any]] = None,
) -> str:
    """Downloads and extract artifact files into destination folder.

    Args:
        artifact_url: url to get artifact from
        nested_program: nested_program object artifact belongs to
        folder: root of nested_programs folder a.k.a unpack destination
        headers: optional headers needed for download requests

    Returns:
        workdir for nested_program
    """
    nested_program_folder_path = os.path.join(folder, nested_program.title)
    artifact_file_name = "artifact"
    tarfile_path = os.path.join(nested_program_folder_path, artifact_file_name)

    # check if nested_program already exist on the disc
    if os.path.exists(nested_program_folder_path):
        logging.warning("NestedProgram folder already exist. Will be overwritten.")

    # download file
    response = requests.get(url=artifact_url, stream=True, headers=headers, timeout=100)
    if not response.ok:
        raise QuantumServerlessException(
            f"Error during fetch of [{artifact_url}] file."
        )

    Path(nested_program_folder_path).mkdir(parents=True, exist_ok=True)

    with open(tarfile_path, "wb") as file:
        for data in response.iter_content():
            file.write(data)

    # unpack tarfile
    with tarfile.open(tarfile_path, "r") as file_obj:
        file_obj.extractall(nested_program_folder_path)

    # delete artifact
    if os.path.exists(tarfile_path):
        os.remove(tarfile_path)
    return nested_program_folder_path
