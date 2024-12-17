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

from qiskit_serverless.core.constants import (
    REQUESTS_STREAMING_TIMEOUT,
    REQUESTS_TIMEOUT,
)
from qiskit_serverless.core.function import QiskitFunction
from qiskit_serverless.exception import QiskitServerlessException
from qiskit_serverless.utils.json import safe_json_request_as_dict


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
        self._files_url = os.path.join(self.host, "api", self.version, "files")

    def _download_with_url(  # pylint:  disable=too-many-positional-arguments
        self,
        file: str,
        download_location: str,
        function: QiskitFunction,
        url: str,
        target_name: Optional[str] = None,
    ) -> Optional[str]:
        """Auxiliar function to download a file using an url."""
        with requests.get(
            url,
            params={
                "file": file,
                "provider": function.provider,
                "function": function.title,
            },
            stream=True,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=REQUESTS_STREAMING_TIMEOUT,
        ) as req:
            req.raise_for_status()

            total_size_in_bytes = int(req.headers.get("content-length", 0))
            chunk_size = 8192
            progress_bar = tqdm(total=total_size_in_bytes, unit="iB", unit_scale=True)
            file_name = target_name or f"downloaded_{str(uuid.uuid4())[:8]}_{file}"
            with open(os.path.join(download_location, file_name), "wb") as f:
                for chunk in req.iter_content(chunk_size=chunk_size):
                    progress_bar.update(len(chunk))
                    f.write(chunk)
            progress_bar.close()
            return file_name

    def download(
        self,
        file: str,
        download_location: str,
        function: QiskitFunction,
        target_name: Optional[str] = None,
    ) -> Optional[str]:
        """Downloads user file."""
        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("files.download"):
            return self._download_with_url(
                file,
                download_location,
                function,
                target_name,
                os.path.join(self._files_url, "download"),
            )

    def provider_download(
        self,
        file: str,
        download_location: str,
        function: QiskitFunction,
        target_name: Optional[str] = None,
    ) -> Optional[str]:
        """Downloads provider file."""
        if not function.provider:
            raise QiskitServerlessException("`function` doesn't have a provider.")

        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("files.provider_download"):
            return self._download_with_url(
                file,
                download_location,
                function,
                target_name,
                os.path.join(self._files_url, "provider", "download"),
            )

    def upload(
        self, file: str, function: QiskitFunction, provider: Optional[str] = None
    ) -> Optional[str]:
        """Uploads file."""
        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("files.upload"):
            with open(file, "rb") as f:
                with requests.post(
                    os.path.join(self._files_url, "upload"),
                    files={"file": f},
                    data={"provider": provider, "function": function.title},
                    stream=True,
                    headers={"Authorization": f"Bearer {self._token}"},
                    timeout=REQUESTS_STREAMING_TIMEOUT,
                ) as req:
                    if req.ok:
                        return req.text
                    return "Upload failed"
            return "Can not open file"

    def provider_upload(
        self, file: str, function: QiskitFunction, provider: str
    ) -> Optional[str]:
        """Uploads file to provider/function file storage."""
        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("files.upload"):
            with open(file, "rb") as f:
                with requests.post(
                    os.path.join(self._files_url, "upload"),
                    files={"file": f},
                    data={"provider": provider, "function": function.title},
                    stream=True,
                    headers={"Authorization": f"Bearer {self._token}"},
                    timeout=REQUESTS_STREAMING_TIMEOUT,
                ) as req:
                    if req.ok:
                        return req.text
                    return "Upload failed"
            return "Can not open file"

    def list(self, function: QiskitFunction) -> List[str]:
        """Returns list of available files to download produced by programs,"""
        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("files.list"):
            response_data = safe_json_request_as_dict(
                request=lambda: requests.get(
                    self._files_url,
                    params={"title": function.title},
                    headers={"Authorization": f"Bearer {self._token}"},
                    timeout=REQUESTS_TIMEOUT,
                )
            )
        return response_data.get("results", [])

    def provider_list(self, function: QiskitFunction) -> List[str]:
        """Returns list of available files to download produced by programs,"""
        if not function.provider:
            raise QiskitServerlessException("`function` doesn't have a provider.")

        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("files.provider_list"):
            response_data = safe_json_request_as_dict(
                request=lambda: requests.get(
                    os.path.join(self._files_url, "provider"),
                    params={"provider": function.provider, "title": function.title},
                    headers={"Authorization": f"Bearer {self._token}"},
                    timeout=REQUESTS_TIMEOUT,
                )
            )
        return response_data.get("results", [])

    def delete(self, file: str, provider: Optional[str] = None) -> Optional[str]:
        """Deletes file uploaded or produced by the programs,"""
        tracer = trace.get_tracer("client.tracer")
        with tracer.start_as_current_span("files.delete"):
            response_data = safe_json_request_as_dict(
                request=lambda: requests.delete(
                    os.path.join(self._files_url, "delete"),
                    data={"file": file, "provider": provider},
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "format": "json",
                    },
                    timeout=REQUESTS_TIMEOUT,
                )
            )
        return response_data.get("message", "")
