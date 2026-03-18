from qiskit import QuantumCircuit
from qiskit.primitives import StatevectorSampler as Sampler

from qiskit_serverless import send_error

send_error(
    code=1000, error_type="MyPersonalizedError", message="My error message", args={"my-arg-1": 123, "my-arg-2": "hi"}
)
