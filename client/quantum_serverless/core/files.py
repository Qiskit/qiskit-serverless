# This code is a Qiskit project.
#
# (C) Copyright IBM 2023.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.


"""
===============================================
Provider (:mod:`quantum_serverless.core.files`)
==============================================

.. currentmodule:: quantum_serverless.core.files

Quantum serverless files
========================

.. autosummary::
    :toctree: ../stubs/

"""
import os.path
from typing import List

import requests
from opentelemetry import trace

from quantum_serverless.core.constants import REQUESTS_TIMEOUT
from quantum_serverless.utils.json import safe_json_request


def download(url: str, local_file_path: str, token: str):
    """Downloads file from url.

    Args:
        url: url
        local_file_path: file destination
        token: auth token
    """
    with requests.get(
        url,
        stream=True,
        headers={"Authorization": f"Bearer {token}"},
        timeout=REQUESTS_TIMEOUT,
    ) as req:
        req.raise_for_status()
        with open(local_file_path, "wb") as f:
            for chunk in req.iter_content(chunk_size=8192):
                f.write(chunk)


class GatewayFilesClient:
    """GatewayFilesClient."""

    def __init__(self, host: str, token: str, version: str):
        """Files client for Gateway service.

        Args:
            host: gateway host
            version: gateway version
            token: authorization token
        """
        self.host = host
        self.version = version
        self._token = token

    def download(self, file: str, directory: str):
        """Downloads file."""
        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("files.download"):
            safe_json_request(
                request=lambda: download(
                    url=f"{self.host}/api/{self.version}/files/{file}",
                    local_file_path=os.path.join(directory, f"downloaded_{file}"),
                    token=self._token,
                ),
            )

    def list(self) -> List[str]:
        """Returns list of available files to download produced by programs,"""
        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("files.list"):
            response_data = safe_json_request(
                request=lambda: requests.get(
                    f"{self.host}/api/{self.version}/files/",
                    headers={"Authorization": f"Bearer {self._token}"},
                    timeout=REQUESTS_TIMEOUT,
                )
            )
        return response_data.get("results", [])
