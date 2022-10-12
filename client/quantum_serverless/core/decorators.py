# This code is part of Qiskit.
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
======================================================
Decorators (:mod:`quantum_serverless.core.decorators`)
======================================================

.. currentmodule:: quantum_serverless.core.decorators

Quantum serverless decorators
=============================

.. autosummary::
    :toctree: ../stubs/

    get
    put
    run_qiskit_remote
"""
from dataclasses import dataclass
from typing import Optional, Dict, Any, Union

import ray

from quantum_serverless.utils import JsonSerializable

remote = ray.remote
get = ray.get
put = ray.put


@dataclass
class Target(JsonSerializable):
    """Quantum serverless target.

    Example:
        >>> @run_qiskit_remote(target=Target(cpu=1))
        >>> def awesome_function():
        >>>     return 42
    """

    cpu: int = 1
    gpu: int = 0
    qpu: int = 0
    mem: int = 1
    resources: Optional[Dict[str, float]] = None
    env_vars: Optional[Dict[str, Any]] = None

    @classmethod
    def from_dict(cls, dictionary: dict):
        return Target(**dictionary)


def run_qiskit_remote(target: Optional[Union[Dict[str, Any], Target]] = None):
    """Wraps local function as remote executable function.
    New function will return reference object when called.

    Example:
        >>> import quantum_serverless as qs
        >>>
        >>> @run_qiskit_remote()
        >>> def awesome_function(seed: int):
        >>>     return 42
        >>>
        >>> reference = awesome_function()
        >>> function_result = qs.get(reference)

    Args:
        target: target object or dictionary for requirements for node resources

    Returns:
        object reference
    """
    if target is None:
        target = Target(cpu=1)

    if not isinstance(target, Target):
        target = Target.from_dict(target)

    def decorator(function):
        def wrapper(*args, **kwargs):
            result = ray.remote(
                num_cpus=target.cpu,
                num_gpus=target.gpu,
                resources=target.resources,
                memory=target.mem,
                runtime_env={"env_vars": target.env_vars},
            )(function).remote(*args, **kwargs)

            return result

        return wrapper

    return decorator
