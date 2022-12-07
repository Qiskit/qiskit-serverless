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
    get_refs_by_status
"""
import os
from dataclasses import dataclass
from typing import Optional, Dict, Any, Union, List

import ray

from quantum_serverless.core.constrants import (
    META_TOPIC,
    QS_EXECUTION_WORKLOAD_ID,
    QS_EXECUTION_UID,
)
from quantum_serverless.core.events import (
    RedisEventHandler,
    ExecutionMessage,
    EventHandler,
)
from quantum_serverless.core.state import StateHandler
from quantum_serverless.utils import JsonSerializable

remote = ray.remote
get = ray.get
put = ray.put
get_refs_by_status = ray.wait


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
    pip: Optional[List[str]] = None

    @classmethod
    def from_dict(cls, dictionary: dict):
        return Target(**dictionary)


def run_qiskit_remote(
    target: Optional[Union[Dict[str, Any], Target]] = None,
    state: Optional[StateHandler] = None,
    events: Optional[EventHandler] = None,
):
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
        state: state handler
        events: events handler

    Returns:
        object reference
    """
    if target is None:
        target = Target(cpu=1)

    if isinstance(target, Target):
        remote_target = target
    else:
        remote_target = Target.from_dict(target)

    runtime_env: Dict[str, Any] = {"env_vars": remote_target.env_vars}
    if remote_target.pip is not None:
        runtime_env["pip"] = remote_target.pip

    def decorator(function):
        def wrapper(*args, **kwargs):
            # inject state as an argument when passed in decorator
            if state is not None:
                args = tuple([state] + list(args))

            # inject execution meta emitter
            if events is not None:
                emitter = events
            else:
                emitter = RedisEventHandler.from_env_vars()
            if emitter is not None:
                emitter.publish(
                    META_TOPIC,
                    message=ExecutionMessage(
                        workload_id=os.environ.get(QS_EXECUTION_WORKLOAD_ID),
                        uid=os.environ.get(QS_EXECUTION_UID),
                        layer="qs",
                        function_meta={"name": function.__name__},
                        resources=remote_target.to_dict(),
                    ).to_dict(),
                )

            result = ray.remote(
                num_cpus=remote_target.cpu,
                num_gpus=remote_target.gpu,
                resources=remote_target.resources,
                memory=remote_target.mem,
                runtime_env=runtime_env,
            )(function).remote(*args, **kwargs)

            return result

        return wrapper

    return decorator
