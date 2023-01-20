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

QISKIT_RUNTIME_ACCOUNT_CONFIG_KEY = "qiskit_runtime_account"
QISKIT_RUNTIME_BACKENDS_CONFIG_KEY = "qiskit_runtime_backends_configs"


class QiskitTrainerException(Exception):
    """QiskitTrainerException."""


@dataclass
class QiskitScalingConfig(ScalingConfig):
    """Scaling configuration for trainer uses Qiskit Runtime service."""

    num_qubits: int = 0
    simulator: bool = False


class QiskitTorchTrainer(TorchTrainer):
    """QiskitTorchTrainer."""

    _scaling_config_allowed_keys = TorchTrainer._scaling_config_allowed_keys + [
        "num_qubits",
        "simulator",
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
            >>> trainer = QiskitTorchTrainer(
            >>>     train_loop_per_worker=...,
            >>>     qiskit_runtime_service_account=QiskitRuntimeService().active_account(),
            >>>     scaling_config=QiskitScalingConfig(num_workers=3, num_qubits=5),
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

        if (
            qiskit_runtime_service_account is not None
            and scaling_config is not None
            and scaling_config.num_qubits > 0
            and scaling_config.num_workers is not None
        ):
            if not isinstance(scaling_config.num_workers, int):
                raise QiskitTrainerException(
                    "Only integer num_worker supported at this moment."
                )
            num_workers: int = scaling_config.num_workers

            qiskit_runtime_service = QiskitRuntimeService(
                **qiskit_runtime_service_account
            )

            # select least busy backends that meets scaling config
            backends = qiskit_runtime_service.backends(
                min_num_qubits=scaling_config.num_qubits,
                simulator=scaling_config.simulator,
                operational=True,
            )[:num_workers]

            if len(backends) < num_workers:
                raise QiskitTrainerException(
                    f"There not enough available backends "
                    f"[{len(backends)}] to meet worker "
                    f"requirement [{num_workers}]"
                )

            # adding qiskit runtime session information to configuration
            updated_train_loop_config[QISKIT_RUNTIME_BACKENDS_CONFIG_KEY] = [
                backend.name for backend in backends
            ]
            updated_train_loop_config[
                QISKIT_RUNTIME_ACCOUNT_CONFIG_KEY
            ] = qiskit_runtime_service.active_account()

        super().__init__(
            train_loop_per_worker,
            train_loop_config=updated_train_loop_config,
            scaling_config=scaling_config,
            **kwargs,
        )


def get_runtime_session(config: Dict) -> Optional[Session]:
    """Returns Qiskit Runtime Session object based on train loop configuration.

    Args:
        config: train loop configuration

    Returns:
        Qiskit Runtime session with allocated backend
    """
    qiskit_runtime_backends: Optional[List[str]] = config.get(
        QISKIT_RUNTIME_BACKENDS_CONFIG_KEY
    )
    qiskit_runtime_account: Optional[Dict[str, Any]] = config.get(
        QISKIT_RUNTIME_ACCOUNT_CONFIG_KEY
    )
    runtime_session = None
    if qiskit_runtime_backends is not None and qiskit_runtime_account is not None:
        worker_id = session.get_world_rank()
        if len(qiskit_runtime_backends) < worker_id:
            raise QiskitTrainerException(
                "There is not qiskit runtime session data in configuration."
            )

        backend = qiskit_runtime_backends[worker_id]
        runtime_service = QiskitRuntimeService(**qiskit_runtime_account)
        runtime_session = Session(service=runtime_service, backend=backend)

    return runtime_session
