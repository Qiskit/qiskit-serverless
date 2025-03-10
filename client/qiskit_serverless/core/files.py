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
from tqdm import tqdm

from qiskit_serverless.core.constants import (
    REQUESTS_STREAMING_TIMEOUT,
    REQUESTS_TIMEOUT,
)
from qiskit_serverless.core.decorators import trace_decorator_factory
from qiskit_serverless.core.function import QiskitFunction
from qiskit_serverless.exception import QiskitServerlessException
from qiskit_serverless.utils.http import get_headers
from qiskit_serverless.utils.json import safe_json_request_as_dict


_trace = trace_decorator_factory("files")


class GatewayFilesClient:
    """GatewayFilesClient."""

    def __init__(
        self, host: str, token: str, version: str, instance: Optional[str] = None
    ):
        """Files client for Gateway service.

        Args:
            host: gateway host
            version: gateway version
            token: authorization token
            instance: IBM Cloud CRN
        """
        self.host = host
        self.version = version
        self._token = token
        self._instance = instance
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
            headers=get_headers(token=self._token, instance=self._instance),
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

    @_trace
    def download(
        self,
        file: str,
        download_location: str,
        function: QiskitFunction,
        target_name: Optional[str] = None,
    ) -> Optional[str]:
        """Download a file available to the user for the specific Qiskit Function."""
        return self._download_with_url(
            file,
            download_location,
            function,
            os.path.join(self._files_url, "download"),
            target_name,
        )

    @_trace
    def provider_download(
        self,
        file: str,
        download_location: str,
        function: QiskitFunction,
        target_name: Optional[str] = None,
    ) -> Optional[str]:
        """Download a file available to the provider for the specific Qiskit Function."""
        if not function.provider:
            raise QiskitServerlessException("`function` doesn't have a provider.")

        return self._download_with_url(
            file,
            download_location,
            function,
            os.path.join(self._files_url, "provider", "download"),
            target_name,
        )

    @_trace
    def upload(self, file: str, function: QiskitFunction) -> Optional[str]:
        """Uploads a file in the specific user's Qiskit Function folder."""
        with open(file, "rb") as f:
            with requests.post(
                os.path.join(self._files_url, "upload/"),
                files={"file": f},
                params={"provider": function.provider, "function": function.title},
                stream=True,
                headers=get_headers(token=self._token, instance=self._instance),
                timeout=REQUESTS_STREAMING_TIMEOUT,
            ) as req:
                if req.ok:
                    return req.text
                return "Upload failed"
        return "Can not open file"

    @_trace
    def provider_upload(self, file: str, function: QiskitFunction) -> Optional[str]:
        """Uploads a file in the specific provider's Qiskit Function folder."""
        if not function.provider:
            raise QiskitServerlessException("`function` doesn't have a provider.")

        with open(file, "rb") as f:
            with requests.post(
                os.path.join(self._files_url, "provider", "upload/"),
                files={"file": f},
                params={"provider": function.provider, "function": function.title},
                stream=True,
                headers=get_headers(token=self._token, instance=self._instance),
                timeout=REQUESTS_STREAMING_TIMEOUT,
            ) as req:
                if req.ok:
                    return req.text
                return "Upload failed"
        return "Can not open file"

    @_trace
    def list(self, function: QiskitFunction) -> List[str]:
        """Returns the list of files available for the user in the Qiskit Function folder."""
        response_data = safe_json_request_as_dict(
            request=lambda: requests.get(
                self._files_url,
                params={"function": function.title, "provider": function.provider},
                headers=get_headers(token=self._token, instance=self._instance),
                timeout=REQUESTS_TIMEOUT,
            )
        )
        return response_data.get("results", [])

    @_trace
    def provider_list(self, function: QiskitFunction) -> List[str]:
        """Returns the list of files available for the provider in the Qiskit Function folder."""
        if not function.provider:
            raise QiskitServerlessException("`function` doesn't have a provider.")

        response_data = safe_json_request_as_dict(
            request=lambda: requests.get(
                os.path.join(self._files_url, "provider"),
                params={"function": function.title, "provider": function.provider},
                headers=get_headers(token=self._token, instance=self._instance),
                timeout=REQUESTS_TIMEOUT,
            )
        )
        return response_data.get("results", [])

    @_trace
    def delete(self, file: str, function: QiskitFunction) -> Optional[str]:
        """Deletes a file available to the user for the specific Qiskit Function."""
        headers = get_headers(token=self._token, instance=self._instance)
        headers["format"] = "json"
        response_data = safe_json_request_as_dict(
            request=lambda: requests.delete(
                os.path.join(self._files_url, "delete"),
                params={
                    "file": file,
                    "function": function.title,
                    "provider": function.provider,
                },
                headers=headers,
                timeout=REQUESTS_TIMEOUT,
            )
        )
        return response_data.get("message", "")

    @_trace
    def provider_delete(self, file: str, function: QiskitFunction) -> Optional[str]:
        """Deletes a file available to the provider for the specific Qiskit Function."""
        if not function.provider:
            raise QiskitServerlessException("`function` doesn't have a provider.")

        headers = get_headers(token=self._token, instance=self._instance)
        headers["format"] = "json"
        response_data = safe_json_request_as_dict(
            request=lambda: requests.delete(
                os.path.join(self._files_url, "provider", "delete"),
                params={
                    "file": file,
                    "function": function.title,
                    "provider": function.provider,
                },
                headers=headers,
                timeout=REQUESTS_TIMEOUT,
            )
        )
        return response_data.get("message", "")
