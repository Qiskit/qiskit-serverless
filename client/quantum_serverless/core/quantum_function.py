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
Provider (:mod:`quantum_serverless.core.quantum_function`)
========================================================

.. currentmodule:: quantum_serverless.core.quantum_function

Quantum serverless quantum function
========================================

.. autosummary::
    :toctree: ../stubs/

    QuantumFunction
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
class QuantumFunction:  # pylint: disable=too-many-instance-attributes
    """Serverless quantum function.

    Args:
        title: quantum function name
        entrypoint: is a script that will be executed as a job
            ex: job.py
        arguments: arguments for entrypoint script
        env_vars: env vars
        dependencies: list of python dependencies to execute a quantum function
        working_dir: directory where entrypoint file is located
        description: description of a quantum function
        version: version of a quantum function
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
        """Reconstructs QuantumFunction from dictionary."""
        field_names = set(f.name for f in dataclasses.fields(QuantumFunction))
        return QuantumFunction(**{k: v for k, v in data.items() if k in field_names})

    def __post_init__(self):
        if self.arguments is not None and not is_jsonable(self.arguments):
            raise QuantumServerlessException(
                "Arguments provided are not json serializable."
            )


class QuantumFunctionStorage(ABC):
    """Base quantum function backend to save and load quantum functions from."""

    def save_quantum_function(self, quantum_function: QuantumFunction) -> bool:
        """Save quantum function in specified backend.

        Args:
            quantum_function: quantum function object

        Returns:
            success state
        """
        raise NotImplementedError

    def get_quantum_functions(self, **kwargs) -> List[str]:
        """Returns list of available quantum functions to get.

        Args:
            kwargs: filtering criteria

        Returns:
            List of names of quantum functions
        """
        raise NotImplementedError

    def get_quantum_function(self, title: str, **kwargs) -> Optional[QuantumFunction]:
        """Returns quantum function by name and other query criteria.

        Args:
            title: title of the quantum_function
            **kwargs: other args

        Returns:
            QuantumFunction
        """
        raise NotImplementedError


class QuantumFunctionRepository(QuantumFunctionStorage):
    """QuantumFunctionRepository."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        token: Optional[str] = None,
        folder: Optional[str] = None,
    ):
        """QuantumFunction repository implementation.

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
        self._base_url = f"{self._host}:{self._port}/v1/api/nested-programs/"

    def save_quantum_function(self, quantum_function: QuantumFunction) -> bool:
        raise NotImplementedError("Not implemented yet.")

    def get_quantum_functions(self, **kwargs) -> List[str]:
        result = []
        response = requests.get(url=self._base_url, params=kwargs, timeout=10)
        if response.ok:
            response_data = json.loads(response.text)
            result = [entry.get("title") for entry in response_data.get("results", [])]
        return result

    def get_quantum_function(self, title: str, **kwargs) -> Optional[QuantumFunction]:
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
                result = QuantumFunction.from_json(results[0])
                result.working_dir = download_and_unpack_artifact(
                    artifact_url=artifact, quantum_function=result, folder=self.folder
                )
            else:
                logging.warning("No entries were found for your request.")
        return result


def download_and_unpack_artifact(
    artifact_url: str,
    quantum_function: QuantumFunction,
    folder: str,
    headers: Optional[Dict[str, Any]] = None,
) -> str:
    """Downloads and extract artifact files into destination folder.

    Args:
        artifact_url: url to get artifact from
        quantum_function: quantum function object artifact belongs to
        folder: root of quantum function folder a.k.a unpack destination
        headers: optional headers needed for download requests

    Returns:
        workdir for quantum function
    """
    quantum_function_folder_path = os.path.join(folder, quantum_function.title)
    artifact_file_name = "artifact"
    tarfile_path = os.path.join(quantum_function_folder_path, artifact_file_name)

    # check if quantum function path already exist on the disc
    if os.path.exists(quantum_function_folder_path):
        logging.warning("QuantumFunction folder already exist. Will be overwritten.")

    # download file
    response = requests.get(url=artifact_url, stream=True, headers=headers, timeout=100)
    if not response.ok:
        raise QuantumServerlessException(
            f"Error during fetch of [{artifact_url}] file."
        )

    Path(quantum_function_folder_path).mkdir(parents=True, exist_ok=True)

    with open(tarfile_path, "wb") as file:
        for data in response.iter_content():
            file.write(data)

    # unpack tarfile
    with tarfile.open(tarfile_path, "r") as file_obj:
        file_obj.extractall(quantum_function_folder_path)

    # delete artifact
    if os.path.exists(tarfile_path):
        os.remove(tarfile_path)
    return quantum_function_folder_path
