import argparse
import ray
import torch
from qiskit_ibm_runtime import QiskitRuntimeService
from ray import train
from ray.air import session
from torch import nn

from quantum_serverless import QuantumServerless, Program
from quantum_serverless.library.train.trainer import (
    QiskitScalingConfig,
    QiskitTorchTrainer,
    get_runtime_sessions,
    assign_backends,
    QiskitTrainerException,
)


def loop(config):
    """Test training loop."""
    # get runtime sessions for this worker
    runtime_session_1, runtime_session_2 = get_runtime_sessions(config)
    
    print("Session for worker:", [runtime_session_1, runtime_session_2])
    print("Available backends for worker", [runtime_session_1.backend(), runtime_session_2.backend()])

    # get data, create QNN and run training loop
    dataset_shard = session.get_dataset_shard("train")
    # ...

    
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--token", help="Token for account.", type=str
    )
    parser.add_argument(
        "--channel",
        help="QiskitRuntimeService channel",
        default="ibm_quantum",
        type=str,
    )

    args = parser.parse_args()
            
    runtime_service = QiskitRuntimeService(
        channel=args.channel,
        token=args.token
    )
    serverless = QuantumServerless()

    with serverless:
        train_dataset = ray.data.from_items(
            [{"x": x, "y": 2 * x + 1} for x in range(200)]
        )
        scaling_config = QiskitScalingConfig(
            num_workers=3,
            resource_filtering={
                "qpu1": {"name": "ibmq_qasm_simulator", "simulator": True},
                "qpu2": {"name": "ibmq_qasm_simulator", "simulator": True},
            },
            allow_overbooking=True
        )
        trainer = QiskitTorchTrainer(
            train_loop_per_worker=loop,
            qiskit_runtime_service_account=runtime_service.active_account(),
            scaling_config=scaling_config,
            datasets={"train": train_dataset},
            train_loop_config={"train_loop_parameter": 1},
            run_config=ray.air.RunConfig(verbose=0)
        )
        result = trainer.fit()
    
    print("Result:", result)
