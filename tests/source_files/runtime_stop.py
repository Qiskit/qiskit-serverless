"""Qiskit Function code that instantiates a service with
get_runtime_service and submits 2 jobs within a session."""

# pylint: disable=duplicate-code

from time import sleep
import warnings
import os

from qiskit import QuantumCircuit
from qiskit_ibm_runtime import SamplerV2, Session

from qiskit_serverless import save_result, get_runtime_service

warnings.filterwarnings(
    "ignore",
    message="Unable to create configuration for*",
    category=UserWarning,
)

print(f"Function: QISKIT_IBM_INSTANCE: {os.environ.get('QISKIT_IBM_INSTANCE')}")
print(f"Function: QISKIT_IBM_TOKEN: {os.environ.get('QISKIT_IBM_TOKEN')[:4]}****")
print(f"Function: QISKIT_IBM_URL: {os.environ.get('QISKIT_IBM_URL')}")
print(f"Function: QISKIT_IBM_BACKEND_1: {os.environ.get('QISKIT_IBM_BACKEND_1')}")

print("getting runtime service")
service = get_runtime_service()

print("getting backends")
backends = service.backends()
backend = service.backend(os.environ["QISKIT_IBM_BACKEND_1"])
session = Session(backend=backend)
sampler = SamplerV2(mode=session)

qc = QuantumCircuit(1)
qc.measure_all()
print("running jobs")
out1 = sampler.run([qc])
out2 = sampler.run([qc])

print("getting job_ids")
job_id_1 = out1.job_id()
job_id_2 = out2.job_id()

# This print is saved in the logs and used in the
# test to determine that the jobs have been submitted
# before stopping them
print("JOB IDS", job_id_1, job_id_2)
sleep(60)
