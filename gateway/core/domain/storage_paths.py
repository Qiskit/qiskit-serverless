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

"""Where the files of a Fleets job live in COS.

Saved in ``JobStoragePaths`` when the job is created, so its files stay readable after a later change to the
layout, the bucket names or the Code Engine project. It lives in ``domain`` because the Fleets path builder
returns it and the storages read it, and the storages already import the builder.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class StoragePaths:  # pylint: disable=too-many-instance-attributes
    """Buckets, data stores, prefixes and keys of one Fleets job.

    The names are copies of the strings on the function's Code Engine project when the job was created, not
    references to it. Keys are bucket-relative. The provider fields are ``None`` for a custom function.
    """

    # Not read yet: only needed if the buckets ever move to another COS instance or region
    cos_region: str
    cos_instance_name: Optional[str]

    user_bucket: str
    provider_bucket: Optional[str]
    # The persistent data stores the prefixes are mounted from at submit
    user_pds: str
    provider_pds: Optional[str]

    # Mount sub-paths, and what the admin lists
    user_function_prefix: str
    user_job_prefix: str
    provider_function_prefix: Optional[str]
    provider_job_prefix: Optional[str]

    # Complete keys. Each sits under its job prefix, see problems()
    arguments_key: str
    results_key: str
    user_log_key: str
    provider_log_key: Optional[str]

    @property
    def is_provider_job(self) -> bool:
        """Whether the job has the provider bucket mounted, which only provider functions do."""
        return self.provider_job_prefix is not None

    def problems(self) -> list[str]:
        """What makes these paths unusable, empty when they are fine to save.

        The container only sees the job prefixes through its mounts, so a key outside them is a file the job can
        never read or write.
        """
        found = [
            f"{name} is not under user_job_prefix"
            for name in ("arguments_key", "results_key", "user_log_key")
            if not getattr(self, name).startswith(self.user_job_prefix + "/")
        ]
        if self.provider_log_key is not None and not self.provider_log_key.startswith(f"{self.provider_job_prefix}/"):
            found.append("provider_log_key is not under provider_job_prefix")
        return found
