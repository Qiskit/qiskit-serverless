# This code is a Qiskit project.
#
# (C) Copyright IBM 2023.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""
=====================================================
Serializers (:mod:`quantum_serverless.train.trainer`)
=====================================================

.. currentmodule:: quantum_serverless.train.trainer

Quantum serverless trainer
==========================

.. autosummary::
    :toctree: ../stubs/

    QiskitScalingConfig
    QiskitTorchTrainer
    get_runtime_session
"""

from dataclasses import dataclass
from typing import Union, Callable, Dict, Optional, List, Any

from qiskit_ibm_runtime import QiskitRuntimeService, Session
from ray.air import session
from ray.air.config import ScalingConfig
from ray.train.torch import TorchTrainer

from quantum_serverless.exception import QuantumServerlessException

QISKIT_RUNTIME_ACCOUNT_CONFIG_KEY = "qiskit_runtime_account"
QISKIT_RUNTIME_BACKENDS_CONFIG_KEY = "qiskit_runtime_backends_configs"


class QiskitTrainerException(QuantumServerlessException):
    """QiskitTrainerException."""


@dataclass
class QiskitScalingConfig(ScalingConfig):
    """Scaling configuration for trainer uses Qiskit Runtime service.

    Each of the worker will get

    Example:
        >>> resource_filtering = {
        >>>     "gpu_a": {"num_qubits": 2, "coupling_map": [[0,1],[1,2]]},
        >>>     "gpu_b": {"num_qubits": 3, "simulator": True},
        >>> }
        >>> scaling_config = QiskitScalingConfig(num_workers=2,
        >>>                                      resource_filtering=resource_filtering)
    """

    resource_filtering: Optional[Dict[str, Dict[str, Any]]] = None
    allow_overbooking: bool = False


def assign_backends(
    available_backends: List[str],
    filter_match: Dict[str, List[str]],
    num_workers: int,
    allow_over_booking: bool = False,
) -> Dict[str, str]:
    """Returns map of assignment backends per config to workers.
    Greedy algorithm.

    Args:
        available_backends: all available backends for account
        filter_match: map of filter to backends available
        num_workers: number of workers
        allow_over_booking: allow backends used more than one time

    Returns:
        map of assigment of resources
    """
    acquire_map = {
        backend: num_workers * len(filter_match) for backend in available_backends
    }

    assignments = {}

    for filter_name, filtered_backends in filter_match.items():
        for worker_idx in range(num_workers):
            filtered_acquire_map = {
                backend: acquire_map[backend] for backend in filtered_backends
            }
            sorted_acquire_map = sorted(
                filtered_acquire_map.items(), key=lambda x: -x[1]
            )
            if len(sorted_acquire_map) == 0 or len(sorted_acquire_map[0]) == 0:
                raise QiskitTrainerException(
                    f"No backends found meeting [{filter_name}] criteria."
                )
            backend_name_to_acquire = sorted_acquire_map[0][0]
            acquire_map[backend_name_to_acquire] -= 1

            assignments[f"{worker_idx}__{filter_name}"] = backend_name_to_acquire

    if not allow_over_booking and any(
        acquisitions < num_workers * len(filter_match) - 1
        for _, acquisitions in acquire_map.items()
    ):
        multiple_acquisitions = [
            backend_name
            for backend_name, acquisitions in acquire_map.items()
            if acquisitions < num_workers * len(filter_match) - 1
        ]
        raise QiskitTrainerException(
            f"Not enough resources to meet all requirements.\n"
            f"Available backends [{available_backends}] are not "
            f"enough to schedule [{num_workers}] workers with given "
            f"filters.\n"
            f"Try setting `allow_over_booking` to `True` "
            f"to allow workers reuse quantum resources."
            f"In that case {multiple_acquisitions} backends will "
            f"be acquired multiple times and shared between workers."
        )

    return assignments


class QiskitTorchTrainer(TorchTrainer):
    """QiskitTorchTrainer."""

    _scaling_config_allowed_keys = TorchTrainer._scaling_config_allowed_keys + [
        "resource_filtering",
        "allow_overbooking",
    ]

    def __init__(
        self,
        train_loop_per_worker: Union[Callable[[], None], Callable[[Dict], None]],
        qiskit_runtime_service_account: Optional[Dict[str, Any]] = None,
        train_loop_config: Optional[Dict] = None,
        scaling_config: Optional[QiskitScalingConfig] = None,
        **kwargs,
    ):
        """Torch trainer with integration of Qiskit Runtime service for parallel QPU execution.

        Example:
            >>> resource_filtering = {
            >>>     "gpu_a": {"num_qubits": 2, "coupling_map": [[0,1],[1,2]]},
            >>>     "gpu_b": {"num_qubits": 3, "simulator": True},
            >>> }
            >>> trainer = QiskitTorchTrainer(
            >>>     train_loop_per_worker=...,
            >>>     qiskit_runtime_service_account=QiskitRuntimeService().active_account(),
            >>>     scaling_config=QiskitScalingConfig(num_workers=3,
            >>>                                        resource_filtering=resource_filtering),
            >>>     datasets={"train": ...}
            >>> )

        Args:
            train_loop_per_worker: train loop function
            qiskit_runtime_service_account: runtime service accout
            train_loop_config: configuration for training loop
            scaling_config: qiskit scaling config
            **kwargs:
        """
        updated_train_loop_config = train_loop_config.copy()

        if not isinstance(scaling_config.num_workers, int):
            raise QiskitTrainerException(
                "Only integer num_worker supported at this moment."
            )
        num_workers: int = scaling_config.num_workers

        if qiskit_runtime_service_account is not None:
            # runtime service data
            qiskit_runtime_service = QiskitRuntimeService(
                **qiskit_runtime_service_account
            )
            updated_train_loop_config[
                QISKIT_RUNTIME_ACCOUNT_CONFIG_KEY
            ] = qiskit_runtime_service.active_account()

            all_available_backends = [
                backend.name for backend in qiskit_runtime_service.backends()
            ]

            matched_resources = {}
            if scaling_config.resource_filtering is None:
                matched_resources["default_qpu"] = all_available_backends
            else:
                # get specific backends for each worker
                for (
                    resource_name,
                    resource_filter,
                ) in scaling_config.resource_filtering.items():
                    resource_backends = qiskit_runtime_service.backends(
                        **resource_filter
                    )
                    matched_resources[resource_name] = [
                        backend.name for backend in resource_backends
                    ]

            # adding qiskit runtime session information to configuration
            updated_train_loop_config[
                QISKIT_RUNTIME_BACKENDS_CONFIG_KEY
            ] = assign_backends(
                available_backends=all_available_backends,
                filter_match=matched_resources,
                num_workers=num_workers,
                allow_over_booking=scaling_config.allow_overbooking,
            )

        super().__init__(
            train_loop_per_worker,
            train_loop_config=updated_train_loop_config,
            scaling_config=scaling_config,
            **kwargs,
        )


def get_runtime_sessions(config: Dict) -> List[Session]:
    """Returns Qiskit Runtime Session object based on train loop configuration.

    Example:
        >>> def train_loop(cfg):
        >>>     ...
        >>>     session_a, session_b = get_runtime_sessions(cfg)

    Args:
        config: train loop configuration

    Returns:
        Qiskit Runtime sessions with allocated backends
    """
    qiskit_runtime_backends: Optional[Dict[str, str]] = config.get(
        QISKIT_RUNTIME_BACKENDS_CONFIG_KEY
    )
    qiskit_runtime_account: Optional[Dict[str, Any]] = config.get(
        QISKIT_RUNTIME_ACCOUNT_CONFIG_KEY
    )
    runtime_sessions = []

    if qiskit_runtime_backends is not None and qiskit_runtime_account is not None:
        worker_id = session.get_world_rank()
        runtime_service = QiskitRuntimeService(**qiskit_runtime_account)

        for key, backend in qiskit_runtime_backends.items():
            worker, _ = key.split("__")

            if worker == str(worker_id):
                runtime_sessions.append(
                    Session(service=runtime_service, backend=backend)
                )

    return runtime_sessions
