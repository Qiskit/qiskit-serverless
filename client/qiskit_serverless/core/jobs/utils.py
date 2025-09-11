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
=============================================
Provider (:mod:`qiskit_serverless.core.jobs`)
=============================================

.. currentmodule:: qiskit_serverless.core.jobs

Qiskit Serverless Job Utils
============================

.. autosummary::
    :toctree: ../stubs/

    save_result
    update_status
    is_running_in_serverless
    is_trial
"""

import json
import logging
import os
from typing import Dict, Any

import ray.runtime_env
import requests

from qiskit_serverless.core.constants import (
    ENV_JOB_GATEWAY_INSTANCE,
    QISKIT_IBM_CHANNEL,
    REQUESTS_TIMEOUT,
    ENV_JOB_GATEWAY_TOKEN,
    ENV_JOB_GATEWAY_HOST,
    ENV_JOB_ID_GATEWAY,
    ENV_GATEWAY_PROVIDER_VERSION,
    GATEWAY_PROVIDER_VERSION_DEFAULT,
    ENV_ACCESS_TRIAL,
)
from qiskit_serverless.serializers.program_serializers import (
    QiskitObjectsEncoder,
)
from qiskit_serverless.utils.http import get_headers
from qiskit_serverless.utils.json import is_jsonable

RuntimeEnv = ray.runtime_env.RuntimeEnv


def save_result(result: Dict[str, Any]):
    """Saves job results.

    Note:
        data passed to save_result function
        must be json serializable (use dictionaries).
        Default serializer is compatible with
        IBM QiskitRuntime provider serializer.
        List of supported types
        [ndarray, QuantumCircuit, Parameter, ParameterExpression,
        NoiseModel, Instruction]. See full list via link.

    Links:
        Source of serializer:
        https://github.com/Qiskit/qiskit-ibm-runtime/blob/0.14.0/qiskit_ibm_runtime/utils/json.py#L197

    Example:
        >>> # save dictionary
        >>> save_result({"key": "value"})
        >>> # save circuit
        >>> circuit: QuantumCircuit = ...
        >>> save_result({"circuit": circuit})
        >>> # save primitives data
        >>> quasi_dists = Sampler.run(circuit).result().quasi_dists
        >>> # {"1x0": 0.1, ...}
        >>> save_result(quasi_dists)

    Args:
        result: data that will be accessible from job handler `.result()` method.
    """

    version = os.environ.get(ENV_GATEWAY_PROVIDER_VERSION)
    if version is None:
        version = GATEWAY_PROVIDER_VERSION_DEFAULT

    token = os.environ.get(ENV_JOB_GATEWAY_TOKEN)
    if token is None:
        logging.warning(
            "Results will be saved as logs since "
            "there is no information about the "
            "authorization token in the environment."
        )
        logging.info("Result: %s", result)
        result_record = json.dumps(result or {}, cls=QiskitObjectsEncoder)
        print(f"\nSaved Result:{result_record}:End Saved Result\n")
        return False

    instance = os.environ.get(ENV_JOB_GATEWAY_INSTANCE, None)
    channel = os.environ.get(QISKIT_IBM_CHANNEL, None)

    if not is_jsonable(result, cls=QiskitObjectsEncoder):
        logging.warning("Object passed is not json serializable.")
        return False

    url = (
        f"{os.environ.get(ENV_JOB_GATEWAY_HOST)}/"
        f"api/{version}/jobs/{os.environ.get(ENV_JOB_ID_GATEWAY)}/result/"
    )
    response = requests.post(
        url,
        data={"result": json.dumps(result or {}, cls=QiskitObjectsEncoder)},
        headers=get_headers(token=token, instance=instance, channel=channel),
        timeout=REQUESTS_TIMEOUT,
    )
    if not response.ok:
        sanitized = response.text.replace("\n", "").replace("\r", "")
        logging.warning("Something went wrong: %s", sanitized)

    return response.ok


def update_status(status: str):
    """Update sub status."""

    version = os.environ.get(ENV_GATEWAY_PROVIDER_VERSION)
    if version is None:
        version = GATEWAY_PROVIDER_VERSION_DEFAULT

    token = os.environ.get(ENV_JOB_GATEWAY_TOKEN)
    if token is None:
        logging.warning(
            "'sub_status' cannot be updated since "
            "there is no information about the "
            "authorization token in the environment."
        )
        return False

    instance = os.environ.get(ENV_JOB_GATEWAY_INSTANCE, None)
    channel = os.environ.get(QISKIT_IBM_CHANNEL, None)

    url = (
        f"{os.environ.get(ENV_JOB_GATEWAY_HOST)}/"
        f"api/{version}/jobs/{os.environ.get(ENV_JOB_ID_GATEWAY)}/sub_status/"
    )
    response = requests.patch(
        url,
        data={"sub_status": status},
        headers=get_headers(token=token, instance=instance, channel=channel),
        timeout=REQUESTS_TIMEOUT,
    )
    if not response.ok:
        sanitized = response.text.replace("\n", "").replace("\r", "")
        logging.warning("Something went wrong: %s", sanitized)

    return response.ok


def is_running_in_serverless() -> bool:
    """Return ``True`` if running as a Qiskit serverless program, ``False`` otherwise."""
    return ENV_JOB_ID_GATEWAY in os.environ


def is_trial() -> bool:
    """Return ``True`` if Job is running in trial mode, ``False`` otherwise."""
    return os.getenv(ENV_ACCESS_TRIAL) == "True"
