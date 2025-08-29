# source_files/program_with_parallel_workflow.py

import os
from qiskit_serverless import save_result, ServerlessRuntimeService

from qiskit import QuantumCircuit
from qiskit.primitives import StatevectorSampler as Sampler

service = ServerlessRuntimeService(
    channel=os.environ["QISKIT_IBM_CHANNEL"],
    instance=os.environ["QISKIT_IBM_INSTANCE"],
    token=os.environ["QISKIT_IBM_TOKEN"]
)

backend = service.backend('test_eagle_us-east')
sampler = Sampler(backend)

qc = QuantumCircuit(1)
qc.measure_all()
out1 = sampler.run([qc])
out2 = sampler.run([qc])

save_result({"results": [out1.result(), out2.result()]})
