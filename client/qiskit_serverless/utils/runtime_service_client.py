# This code is a Qiskit project.
#
# (C) Copyright IBM 2024.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""
======================================================================
Json utilities (:mod:`qiskit_serverless.utils.runtime_service_client`)
======================================================================

.. currentmodule:: qiskit_serverless.utils.runtime_service_client

Qiskit Serverless runtime client wrapper
========================================

.. autosummary::
    :toctree: ../stubs/

    ServerlessRuntimeService
"""
import logging
from typing import Dict, Optional

import requests
from qiskit_ibm_runtime import QiskitRuntimeService
from qiskit_ibm_runtime.runtime_job_v2 import RuntimeJobV2

from qiskit_serverless.core.config import Config
from qiskit_serverless.utils.http import get_headers


def associate_runtime_job_with_serverless_job(
    runtime_job_id: str, session_id: Optional[str] = None
) -> bool:
    """Make a request to gateway to associate runtime job id with serverless job id.

    Args:
        runtime_job_id (str): job id for runtime primitive
        session_id (str): session/batch id

    Returns:
        bool: if request was ok
    """
    version = Config.gateway_provider_version()

    token = Config.job_gateway_token()
    if token is None:
        logging.warning("Runtime job will not be associated with serverless job.")
        return False

    instance = Config.job_gateway_instance()
    channel = Config.qiskit_ibm_channel()

    url = (
        f"{Config.job_gateway_host()}/"
        f"api/{version}/jobs/{Config.job_id_gateway()}/runtime_jobs/"
    )

    response = requests.post(
        url,
        json={"runtime_job": runtime_job_id, "runtime_session": session_id},
        headers=get_headers(token=token, instance=instance, channel=channel),
        timeout=Config.requests_timeout(),
    )
    if not response.ok:
        sanitized = response.text.replace("\n", "").replace("\r", "")
        logging.warning("Something went wrong: %s", sanitized)

    return response.ok


class ServerlessRuntimeService(QiskitRuntimeService):
    """Serverless wrapper for QiskitRuntimeService.

    Used for associating runtime jobs with serverless jobs.
    """

    def _run(
        self,
        program_id: str,
        inputs: Dict,
        *args,
        **kwargs,
    ) -> RuntimeJobV2:
        """Run a job on the associated QiskitRuntimeService."""
        runtime_job = super()._run(
            program_id,
            inputs,
            *args,
            **kwargs,
        )
        associate_runtime_job_with_serverless_job(
            runtime_job.job_id(), runtime_job.session_id
        )
        return runtime_job
