# This code is part of Qiskit.
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

"""Tests for trainer."""
from unittest import TestCase, skip

import ray
import torch
from qiskit_ibm_runtime import QiskitRuntimeService
from ray import train
from ray.air import session
from torch import nn

from quantum_serverless.library.train.trainer import (
    QiskitScalingConfig,
    QiskitTorchTrainer,
    get_runtime_sessions,
    assign_backends,
    QiskitTrainerException,
)

QISKIT_RUNTIME_ACCOUNT_CONFIG_KEY = "qiskit_runtime_account"
QISKIT_RUNTIME_BACKENDS_CONFIG_KEY = "qiskit_runtime_backends_configs"


INPUT_SIZE = 1
LAYER_SIZE = 15
OUTPUT_SIZE = 1
NUM_EPOCHS = 1


# pylint:disable=no-member
class NeuralNetwork(nn.Module):
    """Test neural network."""

    def __init__(self):
        super().__init__()
        self.layer1 = nn.Linear(INPUT_SIZE, LAYER_SIZE)
        self.relu = nn.ReLU()
        self.layer2 = nn.Linear(LAYER_SIZE, OUTPUT_SIZE)

    def forward(self, input_tensor):
        """Forward pass."""
        return self.layer2(self.relu(self.layer1(input_tensor)))


def loop(config):
    """Test training loop."""
    runtime_sessions = get_runtime_sessions(config)
    print(runtime_sessions)

    dataset_shard = session.get_dataset_shard("train")
    model = NeuralNetwork()
    loss_fn = nn.MSELoss()
    optimizer = torch.optim.SGD(model.parameters(), lr=0.1)

    model = train.torch.prepare_model(model)

    for epoch in range(NUM_EPOCHS):
        for batches in dataset_shard.iter_torch_batches(
            batch_size=32, dtypes=torch.float
        ):
            inputs, labels = torch.unsqueeze(batches["x"], 1), batches["y"]
            output = model(inputs)
            loss = loss_fn(output, labels)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            print(f"epoch: {epoch}, loss: {loss.item()}")


class TestTrainer(TestCase):
    """Tests for trainer."""

    def test_backend_assignment(self):
        """Tests backends assignments."""
        assignment_default = assign_backends(
            available_backends=[f"backend{idx}" for idx in range(10)],
            filter_match={
                "filter1": [f"backend{idx}" for idx in range(0, 5)],
                "filter2": [f"backend{idx}" for idx in range(6, 9)],
            },
            num_workers=3,
        )
        expecting_assignments_default = {
            "0__filter1": "backend0",
            "1__filter1": "backend1",
            "2__filter1": "backend2",
            "0__filter2": "backend6",
            "1__filter2": "backend7",
            "2__filter2": "backend8",
        }
        self.assertEqual(
            assignment_default, expecting_assignments_default, "No overbooking case."
        )

        # with overbooking allowed
        assignment_with_overbooking = assign_backends(
            available_backends=[f"backend{idx}" for idx in range(10)],
            filter_match={
                "filter1": [f"backend{idx}" for idx in range(0, 5)],
                "filter2": [f"backend{idx}" for idx in range(2, 4)],
            },
            num_workers=3,
            allow_over_booking=True,
        )
        expecting_assignments_with_overbooking = {
            "0__filter1": "backend0",
            "1__filter1": "backend1",
            "2__filter1": "backend2",
            "0__filter2": "backend3",
            "1__filter2": "backend2",
            "2__filter2": "backend3",
        }
        self.assertEqual(
            assignment_with_overbooking,
            expecting_assignments_with_overbooking,
            "With overbooking allowed.",
        )

        # should throw error as assignment with overbooking
        with self.assertRaises(QiskitTrainerException):
            assign_backends(
                available_backends=[f"backend{idx}" for idx in range(10)],
                filter_match={
                    "filter1": [f"backend{idx}" for idx in range(0, 5)],
                    "filter2": [f"backend{idx}" for idx in range(2, 4)],
                },
                num_workers=3,
                allow_over_booking=False,
            )

    @skip("Call to external resources.")
    def test_trainer(self):
        """Tests trainer."""
        train_dataset = ray.data.from_items(
            [{"x": x, "y": 2 * x + 1} for x in range(200)]
        )
        scaling_config = QiskitScalingConfig(
            num_workers=3,
            resource_filtering={
                "qpu1": {"simulator": True},
                "qpu2": {"simulator": True},
            },
            allow_overbooking=True,
        )
        runtime_service = QiskitRuntimeService()

        trainer = QiskitTorchTrainer(
            train_loop_per_worker=loop,
            qiskit_runtime_service_account=runtime_service.active_account(),
            scaling_config=scaling_config,
            datasets={"train": train_dataset},
            train_loop_config={"bla-bla": 1},
        )
        trainer.fit()
