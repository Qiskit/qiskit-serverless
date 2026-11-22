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
from core.ibm_cloud import get_cos_client_for
from core.ibm_cloud.code_engine.fleets.cos import JobCOS
from core.ibm_cloud.code_engine.fleets.utils import build_fleets_storage_paths
from core.models import CodeEngineProject, Job, JobStoragePaths

logger = logging.getLogger("core.JobStoragePaths")

_FIELDS = [field.name for field in fields(StoragePaths)]


def get_storage_paths(job: Job) -> StoragePaths:
    """The paths saved for the job. Reading them needs only the saved row, not the job's function or project.

    The fallback, for a job without a row (created before the rows were saved, or by an old gateway pod during a
    rollout): its paths are built from today's layout, which is where it wrote its files, and nothing is saved. A data
    migration fills those rows later, and then this fallback can be removed.

    Raises:
        ValueError: If the job has no saved paths and they can't be built (see
            :func:`build_fleets_storage_paths`), for example because its function was deleted.
    """
    try:
        return _from_row(job.storage_paths)
    except JobStoragePaths.DoesNotExist:
        pass

    if not job.program_id:
        raise ValueError(f"Job '{job.id}' has no saved storage paths and its function was deleted")
    logger.info("job_id=%s has no saved storage paths, reading it from today's layout", job.id)
    return build_fleets_storage_paths(job, _project_of(job))


def save_storage_paths(job: Job, paths: StoragePaths) -> JobStoragePaths:
    """Save the paths of a new job. Call it in the transaction that saves the job.

    Raises:
        ValueError: If a key is not under its job prefix.
        IntegrityError: If the job already has saved paths.
    """
    problems = paths.problems()
    if problems:
        raise ValueError(f"Storage paths of job_id={job.id} can't be saved: {', '.join(problems)}")
    row = JobStoragePaths.objects.create(job=job, **asdict(paths))
    job.storage_paths = row
    return row


def get_storage_cos_client(paths: StoragePaths) -> JobCOS:
    """The COS client for the job's files, signed with the HMAC secret of the project saved with its paths."""
    return get_cos_client_for(paths.ce_project_id, paths.cos_region)


def _from_row(row: JobStoragePaths) -> StoragePaths:
    return StoragePaths(**{name: getattr(row, name) for name in _FIELDS})


def _project_of(job: Job) -> CodeEngineProject | None:
    """The project the job was created in: the one named on the job, else its function's current one."""
    if job.ce_project_name:
        project = CodeEngineProject.objects.select_by_name(job.ce_project_name, job.ce_region)
        if project:
            return project
    return job.program.code_engine_project
