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
Provider (:mod:`qiskit_serverless.core.files`)
==============================================

.. currentmodule:: qiskit_serverless.core.files

Qiskit Serverless files
========================

.. autosummary::
    :toctree: ../stubs/

"""
import os.path
import uuid
from typing import List, Optional

import requests
from opentelemetry import trace
from tqdm import tqdm

from qiskit_serverless.core.constants import REQUESTS_TIMEOUT
from qiskit_serverless.utils.json import safe_json_request


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

    def download(
        self,
        file: str,
        download_location: str,
        target_name: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> Optional[str]:
        """Downloads file."""
        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("files.download"):
            with requests.get(
                f"{self.host}/api/{self.version}/files/download/",
                params={"file": file, "provider": provider},
                stream=True,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=REQUESTS_TIMEOUT,
            ) as req:
                req.raise_for_status()

                total_size_in_bytes = int(req.headers.get("content-length", 0))
                chunk_size = 8192
                progress_bar = tqdm(
                    total=total_size_in_bytes, unit="iB", unit_scale=True
                )
                file_name = target_name or f"downloaded_{str(uuid.uuid4())[:8]}_{file}"
                with open(os.path.join(download_location, file_name), "wb") as f:
                    for chunk in req.iter_content(chunk_size=chunk_size):
                        progress_bar.update(len(chunk))
                        f.write(chunk)
                progress_bar.close()
                return file_name

    def upload(self, file: str, provider: Optional[str] = None) -> Optional[str]:
        """Uploads file."""
        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("files.upload"):
            with open(file, "rb") as f:
                with requests.post(
                    f"{self.host}/api/{self.version}/files/upload/",
                    files={"file": f},
                    data={"provider": provider},
                    stream=True,
                    headers={"Authorization": f"Bearer {self._token}"},
                    timeout=REQUESTS_TIMEOUT,
                ) as req:
                    if req.ok:
                        return req.text
                    return "Upload failed"
            return "Can not open file"

    def list(self, provider: Optional[str] = None) -> List[str]:
        """Returns list of available files to download produced by programs,"""
        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("files.list"):
            response_data = safe_json_request(
                request=lambda: requests.get(
                    f"{self.host}/api/{self.version}/files/",
                    params={"provider": provider},
                    headers={"Authorization": f"Bearer {self._token}"},
                    timeout=REQUESTS_TIMEOUT,
                )
            )
        return response_data.get("results", [])

    def delete(self, file: str, provider: Optional[str] = None) -> Optional[str]:
        """Deletes file uploaded or produced by the programs,"""
        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("files.delete"):
            response_data = safe_json_request(
                request=lambda: requests.delete(
                    f"{self.host}/api/{self.version}/files/delete/",
                    data={"file": file, "provider": provider},
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "format": "json",
                    },
                    timeout=REQUESTS_TIMEOUT,
                )
            )
        return response_data.get("message", "")
