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
=================================================
Provider (:mod:`quantum_serverless.core.pattern`)
=================================================

.. currentmodule:: quantum_serverless.core.pattern

Quantum serverless pattern
==========================

.. autosummary::
    :toctree: ../stubs/

    QiskitPattern
"""
import dataclasses
import warnings
from dataclasses import dataclass
from typing import Optional, Dict, List, Any


@dataclass
class QiskitPattern:  # pylint: disable=too-many-instance-attributes
    """Serverless QiskitPattern.

    Args:
        title: program name
        entrypoint: is a script that will be executed as a job
            ex: job.py
        env_vars: env vars
        dependencies: list of python dependencies to execute a program
        working_dir: directory where entrypoint file is located (max size 50MB)
        description: description of a program
        version: version of a program
    """

    title: str
    entrypoint: Optional[str] = None
    working_dir: Optional[str] = "./"
    env_vars: Optional[Dict[str, str]] = None
    dependencies: Optional[List[str]] = None
    description: Optional[str] = None
    version: Optional[str] = None
    tags: Optional[List[str]] = None
    raw_data: Optional[Dict[str, Any]] = None

    @classmethod
    def from_json(cls, data: Dict[str, Any]):
        """Reconstructs QiskitPattern from dictionary."""
        field_names = set(f.name for f in dataclasses.fields(QiskitPattern))
        return QiskitPattern(**{k: v for k, v in data.items() if k in field_names})

    def __str__(self):
        return f"QiskitPattern({self.title})"

    def __repr__(self):
        return self.__str__()


class Program(QiskitPattern):  # pylint: disable=too-few-public-methods
    """[Deprecated] Program"""

    def __init__(
        self,
        title: str,
        entrypoint: Optional[str] = None,
        working_dir: Optional[str] = "./",
        env_vars: Optional[Dict[str, str]] = None,
        dependencies: Optional[List[str]] = None,
        description: Optional[str] = None,
        version: Optional[str] = None,
        tags: Optional[List[str]] = None,
        raw_data: Optional[Dict[str, Any]] = None,
    ):
        """Program."""
        warnings.warn(
            "`Program` has been deprecated and will be removed in future releases. "
            "Please, use `QiskitPattern` instead."
        )
        super().__init__(
            title,
            entrypoint,
            working_dir,
            env_vars,
            dependencies,
            description,
            version,
            tags,
            raw_data,
        )
