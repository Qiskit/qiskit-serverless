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
Provider (:mod:`quantum_serverless.core.job`)
=============================================

.. currentmodule:: quantum_serverless.core.job

Quantum serverless job
======================

.. autosummary::
    :toctree: ../stubs/

    RuntimeEnv
    Job
"""

from typing import Iterator

import ray.runtime_env
from ray.dashboard.modules.job.sdk import JobSubmissionClient

RuntimeEnv = ray.runtime_env.RuntimeEnv


class Job:
    """Job."""

    def __init__(self, job_id: str, job_client: JobSubmissionClient):
        """Job class for async script execution.

        Args:
            job_id: if of the job
            job_client: job client
        """
        self.job_id = job_id
        self._job_client = job_client

    def status(self):
        """Returns status of the job."""
        return self._job_client.get_job_status(self.job_id)

    def stop(self):
        """Stops the job from running."""
        return self._job_client.stop_job(self.job_id)

    def logs(self) -> str:
        """Returns logs of the job."""
        return self._job_client.get_job_logs(self.job_id)

    def logs_iterator(self) -> Iterator[str]:
        """Returns logs iterator."""
        return self._job_client.tail_job_logs(self.job_id)

    def __repr__(self):
        return f"<Job | f{self.job_id}>"
