# This code is part of a Qiskit project.
#
# (C) Copyright IBM 2025
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.
"""
Sampler Function source code.
"""
from __future__ import annotations

from collections.abc import Iterable
import logging
import os
import traceback

import numpy as np

from qiskit import QuantumCircuit
from qiskit.transpiler import generate_preset_pass_manager
from qiskit.primitives import PrimitiveResult
from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2
from qiskit_serverless import ServerlessRuntimeService as QiskitRuntimeService
from qiskit_serverless import get_arguments, save_result, update_status, Job
from qiskit import __version__ as qiskit_version
from qiskit import qpy

logger = logging.getLogger(__name__)


class SamplerFunction:
    """
    Sampler Function for testing and debugging
    """

    def __init__(
        self,
        backend_name: str,
        circuits: Iterable[QuantumCircuit],
    ) -> None:
        """Sampler

        Args:
            backend_name: Name of the backend to use.
            pubs: An iterable of circuits
        Raises:
            ValueError: If input arguments are invalid.
        """
        logger.info(f"QISKIT VERSION {qiskit_version}, QPY VERSION {qpy.QPY_VERSION}")
        # Validate and set input backend
        if not backend_name:
            raise ValueError(f"Invalid backend_name value {backend_name}.")
        if os.environ.get("LOCAL_TESTING", "false").lower() == "true":
            self._service = QiskitRuntimeService(channel="local")
            self._backend = self._service.backend(backend_name)
        else:
            self._service = QiskitRuntimeService(
                channel=os.environ["QISKIT_IBM_CHANNEL"],
                instance=os.environ["QISKIT_IBM_INSTANCE"],
                token=os.environ["QISKIT_IBM_TOKEN"],
            )
            self._backend = self._service.backend(backend_name)

        self._circuits = circuits
        logger.info("Backend used: %s", self._backend.name)

    def run(self) -> PrimitiveResult:
        """Execute the request."""

        update_status(Job.OPTIMIZING_HARDWARE)
        pass_manager = generate_preset_pass_manager(
            backend=self._backend,
            seed_transpiler=0,
        )
        isa_circuits = pass_manager.run(self._circuits)
        isa_pubs = [isa_circuits]

        sampler = SamplerV2(mode=self._backend)

        job = sampler.run(pubs=isa_pubs)
        logger.info("Qiskit Runtime job %s submitted.", job.job_id())

        while job.status() == "QUEUED":
            update_status(Job.WAITING_QPU)

        update_status(Job.EXECUTING_QPU)

        return job.result()


def set_up_logger(my_logger: logging.Logger, level: int = logging.INFO) -> None:
    """Logger setup to communicate logs through serverless."""

    log_fmt = "%(module)s.%(funcName)s:%(levelname)s:%(asctime)s: %(message)s"
    formatter = logging.Formatter(log_fmt)

    # Set propagate to `False` since handlers are to be attached.
    my_logger.propagate = False

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    my_logger.addHandler(stream_handler)
    my_logger.setLevel(level)


if __name__ == "__main__":
    # Use serverless helper function to extract input arguments,
    try:
        input_args = get_arguments()
    except Exception:
        save_result(traceback.format_exc())
        raise

    # Allow to configure logging level
    logging_level = input_args.get("logging_level", logging.INFO)
    set_up_logger(logger, logging_level)

    try:
        func = SamplerFunction(**input_args)
        # Use serverless function to save the results that
        # will be returned in the job.
        result = func.run()
        save_result(result)
    except Exception:
        save_result(traceback.format_exc())
        raise
