"""Qiskit Function code that instantiates a service with
get_runtime_service and submits 2 jobs without a session."""

# pylint: disable=duplicate-code

import warnings
import os

from qiskit import QuantumCircuit
from qiskit_ibm_runtime import SamplerV2

from qiskit_serverless import save_result, get_runtime_service

warnings.filterwarnings(
    "ignore",
    message="Unable to create configuration for*",
    category=UserWarning,
)

print(f"Function: QISKIT_IBM_INSTANCE: {os.environ.get('QISKIT_IBM_INSTANCE')}")
print(
    f"Function: QISKIT_IBM_TOKEN: {os.environ.get('QISKIT_IBM_TOKEN', '****')[:4]}****"
)
print(f"Function: QISKIT_IBM_URL: {os.environ.get('QISKIT_IBM_URL')}")
print(f"Function: QISKIT_IBM_BACKEND_1: {os.environ.get('QISKIT_IBM_BACKEND_1')}")

print("getting runtime service")
service = get_runtime_service()

print("getting backends")
backends = service.backends()
backend = service.backend(os.environ["QISKIT_IBM_BACKEND_1"])
sampler = SamplerV2(backend)


qc = QuantumCircuit(1)
qc.measure_all()
print("running jobs")
out1 = sampler.run([qc])
out2 = sampler.run([qc])

print("getting job_ids")
job_id_1 = out1.job_id()
job_id_2 = out2.job_id()
print("JOB IDS", job_id_1, job_id_2)

save_result(
    {
        "backends": [back.name for back in backends],
        "results": [
            [job_id_1, job_id_2],
            [],
        ],
    }
)
