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

from quantum_serverless.train.trainer import (
    QiskitScalingConfig,
    QiskitTorchTrainer,
    get_runtime_session,
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
    runtime_session = get_runtime_session(config)
    print(runtime_session)

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

    @skip("Call to external resources.")
    def test_trainer(self):
        """Tests trainer."""
        train_dataset = ray.data.from_items(
            [{"x": x, "y": 2 * x + 1} for x in range(200)]
        )
        scaling_config = QiskitScalingConfig(num_workers=3, num_qubits=1)
        runtime_service = QiskitRuntimeService()

        trainer = QiskitTorchTrainer(
            train_loop_per_worker=loop,
            qiskit_runtime_service_account=runtime_service.active_account(),
            scaling_config=scaling_config,
            datasets={"train": train_dataset},
            train_loop_config={"bla-bla": 1},
        )
        trainer.fit()
