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

from django.db import IntegrityError, transaction

from core.domain.storage_paths import StoragePaths
from core.ibm_cloud import get_cos_client, get_cos_client_for
from core.ibm_cloud.code_engine.fleets.cos import JobCOS
from core.ibm_cloud.code_engine.fleets.utils import build_fleets_storage_paths
from core.models import CodeEngineProject, Job, JobStoragePaths

logger = logging.getLogger("core.JobStoragePaths")

_FIELDS = [field.name for field in fields(StoragePaths)]


def get_storage_paths(job: Job) -> StoragePaths:
    """The paths saved for the job. Reading them needs only the saved row, not the job's function or project.

    A job without a row was created by an old gateway pod during a rollout, after the data migration ran. Its paths
    are built once with today's layout, which is what that pod used minutes before, saved, and read from the row from
    then on.

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
    paths = build_fleets_storage_paths(job, _project_of(job))
    logger.warning("job_id=%s had no saved storage paths, saving the ones today's layout gives it", job.id)
    try:
        with transaction.atomic():
            save_storage_paths(job, paths)
    except IntegrityError:
        # Saved by another reader in the meantime: theirs is the row every later read uses
        return _from_row(JobStoragePaths.objects.get(job_id=job.id))
    return paths


def save_storage_paths(job: Job, paths: StoragePaths) -> JobStoragePaths:
    """Save the paths of a job that has none. Call it in the transaction that saves the job.

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


def get_storage_cos_client(job: Job, paths: StoragePaths) -> JobCOS:
    """The COS client for the job's files, signed with the HMAC secret of the project saved with its paths.

    A row saved without a project id (its project could not be found when it was saved) falls back to the function's
    current project, as before the paths were saved.

    Raises:
        ValueError: If there is no saved project id and the function, or its project, is gone.
    """
    if paths.ce_project_id:
        return get_cos_client_for(paths.ce_project_id, paths.cos_region)
    project = job.program.code_engine_project if job.program_id else None
    if not project:
        raise ValueError(f"Job '{job.id}' has no saved Code Engine project and its function has none")
    return get_cos_client(project)


def _from_row(row: JobStoragePaths) -> StoragePaths:
    return StoragePaths(**{name: getattr(row, name) for name in _FIELDS})


def _project_of(job: Job) -> CodeEngineProject | None:
    """The project the job was created in: the one named on the job, else its function's current one."""
    if job.ce_project_name:
        project = CodeEngineProject.objects.select_by_name(job.ce_project_name, job.ce_region)
        if project:
            return project
    return job.program.code_engine_project
