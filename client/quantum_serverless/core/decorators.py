"""Decorators."""
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


def run_qiskit_remote(target: Union[Dict[str, Any], Target]):
    """Wraps local function as remote executable function.
    New function will return reference object when called.

    Example:
        >>> import quantum_serverless as qs
        >>>
        >>> @run_qiskit_remote
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
