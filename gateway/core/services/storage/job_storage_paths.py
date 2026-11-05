# This code is part of a Qiskit project.
#
# (C) IBM 2026
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""Read and save where the files of a Fleets job live (the ``JobStoragePaths`` row)."""

import logging
from dataclasses import asdict, fields

from core.domain.storage_paths import StoragePaths
from core.ibm_cloud.code_engine.fleets.utils import build_fleets_storage_paths
from core.models import Job, JobStoragePaths

logger = logging.getLogger("core.JobStoragePaths")

_FIELDS = [field.name for field in fields(StoragePaths)]


def get_storage_paths(job: Job) -> StoragePaths:
    """The paths saved for the job, or the ones today's layout gives a job that has none.

    A job has none when it was created before the paths were saved, and the backfill has not reached it yet, or
    when an old gateway pod created it during a rollout.

    Raises:
        ValueError: If the job has no saved paths and they can't be built (see
            :func:`build_fleets_storage_paths`).
    """
    try:
        row = job.storage_paths
    except JobStoragePaths.DoesNotExist:
        logger.debug("job_id=%s has no saved storage paths, building them with today's layout", job.id)
        return build_fleets_storage_paths(job)
    return StoragePaths(**{name: getattr(row, name) for name in _FIELDS})


def save_storage_paths(job: Job, paths: StoragePaths) -> JobStoragePaths:
    """Save the paths of a job that has none. Call it in the transaction that saves the job.

    Raises:
        ValueError: If a key is not under its job prefix.
        IntegrityError: If the job already has saved paths.
    """
    problems = paths.problems()
    if problems:
        raise ValueError(f"Storage paths of job_id={job.id} can't be saved: {', '.join(problems)}")
    return JobStoragePaths.objects.create(job=job, **asdict(paths))
