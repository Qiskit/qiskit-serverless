from qiskit import QuantumCircuit
from qiskit.primitives import StatevectorSampler as Sampler

from qiskit_serverless import send_error

send_error(1000, "My error message", {"my-arg-1": 123, "my-arg-2": "hi"})
