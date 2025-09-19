# source_files/pattern_with_runtime_wrapper.py

import os
import warnings
from qiskit_serverless import save_result, ServerlessRuntimeService
from qiskit_serverless.utils.runtime_service_client import (
    associate_runtime_job_with_serverless_job,
)
from qiskit import QuantumCircuit
from qiskit_ibm_runtime import SamplerV2

warnings.filterwarnings(
    "ignore",
    message="Unable to create configuration for*",
    category=UserWarning,
)

service = ServerlessRuntimeService(
    channel=os.environ["QISKIT_IBM_CHANNEL"],
    instance=os.environ["QISKIT_IBM_INSTANCE"],
    token=os.environ["QISKIT_IBM_TOKEN"],
    url="https://test.cloud.ibm.com",
)


backends = service.backends()
backend = service.backend("test_eagle")
sampler = SamplerV2(backend)

qc = QuantumCircuit(1)
qc.measure_all()
out1 = sampler.run([qc])
out2 = sampler.run([qc])

job_id_1 = out1.job_id()
job_id_2 = out2.job_id()

# print(
#     "outside associate ok??",
#     associate_runtime_job_with_serverless_job(
#         job_id_1, ""
#     ),
# )

print("JOB IDS:", out1.job_id(), out2.job_id())
print("RESULT 1:", out1.result())
print("RESULT 2:", out2.result())

save_result(
    {
        "backends": [back.name for back in backends],
        "results": [out1.job_id(), out2.job_id()],
    }
)
