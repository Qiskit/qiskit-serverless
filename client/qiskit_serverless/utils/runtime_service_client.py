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
import os
import logging
from typing import Callable, Dict, Sequence, Type, Union, Optional

import requests
from qiskit_ibm_runtime import QiskitRuntimeService
from qiskit_ibm_runtime.runtime_job import RuntimeJob
from qiskit_ibm_runtime.runtime_job_v2 import RuntimeJobV2
from qiskit_ibm_runtime.runtime_options import RuntimeOptions
from qiskit_ibm_runtime.utils.result_decoder import ResultDecoder

from qiskit_serverless.core.constants import (
    ENV_JOB_GATEWAY_INSTANCE,
    REQUESTS_TIMEOUT,
    ENV_JOB_GATEWAY_TOKEN,
    ENV_JOB_GATEWAY_HOST,
    ENV_JOB_ID_GATEWAY,
    ENV_GATEWAY_PROVIDER_VERSION,
    GATEWAY_PROVIDER_VERSION_DEFAULT,
)
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
    version = os.environ.get(ENV_GATEWAY_PROVIDER_VERSION)
    if version is None:
        version = GATEWAY_PROVIDER_VERSION_DEFAULT

    token = os.environ.get(ENV_JOB_GATEWAY_TOKEN)
    if token is None:
        logging.warning("Runtime job will not be associated with serverless job.")
        return False

    instance = os.environ.get(ENV_JOB_GATEWAY_INSTANCE, None)

    url = (
        f"{os.environ.get(ENV_JOB_GATEWAY_HOST)}/"
        f"api/{version}/jobs/{os.environ.get(ENV_JOB_ID_GATEWAY)}/add_runtimejob/"
    )
    response = requests.post(
        url,
        json={"runtime_job": runtime_job_id, "runtime_session": session_id},
        headers=get_headers(token=token, instance=instance),
        timeout=REQUESTS_TIMEOUT,
    )
    if not response.ok:
        sanitized = response.text.replace("\n", "").replace("\r", "")
        logging.warning("Something went wrong: %s", sanitized)

    return response.ok


class ServerlessRuntimeService(QiskitRuntimeService):
    """Serverless wrapper for QiskitRuntimeService.

    Used for associating runtime jobs with serverless jobs.

    Args:
        QiskitRuntimeService (QiskitRuntimeService): Qiskit runtime service object.
    """

    def run(  # pylint:  disable=too-many-positional-arguments
        self,
        program_id: str,
        inputs: Dict,
        options: Optional[Union[RuntimeOptions, Dict]] = None,
        callback: Optional[Callable] = None,
        result_decoder: Optional[
            Union[Type[ResultDecoder], Sequence[Type[ResultDecoder]]]
        ] = None,
        session_id: Optional[str] = None,
        start_session: Optional[bool] = False,
    ) -> Union[RuntimeJob, RuntimeJobV2]:
        """Run a serverless Runtime service job."""
        runtime_job = super()._run(
            program_id,
            inputs,
            options,
            callback,
            result_decoder,
            session_id,
            start_session,
        )
        associate_runtime_job_with_serverless_job(
            runtime_job.job_id(), runtime_job.session_id
        )
        return runtime_job
