"""Default entrypoint."""
import os
import traceback
import requests

from qiskit_serverless import get_arguments, save_result
from qiskit_serverless import ServerlessRuntimeService
from qiskit_ibm_runtime import Sampler, QiskitRuntimeService

from qiskit_serverless.core.constants import (
    ENV_JOB_GATEWAY_INSTANCE,
    QISKIT_IBM_CHANNEL,
    REQUESTS_TIMEOUT,
    ENV_JOB_GATEWAY_TOKEN,
    ENV_JOB_GATEWAY_HOST,
    ENV_JOB_ID_GATEWAY,
    ENV_GATEWAY_PROVIDER_VERSION,
    GATEWAY_PROVIDER_VERSION_DEFAULT,
)

from qiskit_serverless.utils.http import get_headers

def get_associated_runtime_job():
    version = os.environ.get(ENV_GATEWAY_PROVIDER_VERSION, GATEWAY_PROVIDER_VERSION_DEFAULT)
    token = os.environ.get(ENV_JOB_GATEWAY_TOKEN)
    instance = os.environ.get(ENV_JOB_GATEWAY_INSTANCE)
    channel = os.environ.get(QISKIT_IBM_CHANNEL)
    job_id = os.environ.get(ENV_JOB_ID_GATEWAY)
    host = os.environ.get(ENV_JOB_GATEWAY_HOST)

    url = f"{host}/api/{version}/jobs/{job_id}/list_runtimejob/"

    response = requests.get(
        url,
        headers=get_headers(token=token, instance=instance, channel=channel),
        timeout=REQUESTS_TIMEOUT,
    )
    print(response)
    if response.ok:
        job_info = response.json()
        print("Runtime job ID:", job_info.get("runtime_job"))
    else:
        print("Failed to retrieve job info:", response.status_code, response.text)


class Runner:

    def __init__(self):
        self.service = ServerlessRuntimeService(
            channel=os.environ["QISKIT_IBM_CHANNEL"],
            instance=os.environ["QISKIT_IBM_INSTANCE"],
            token=os.environ["QISKIT_IBM_TOKEN"]
        ) # same as QiskitRuntimeService

        # from qiskit_serverless import get_service
        # self.service = get_service()



    def run(self, *args, **kwargs):
        print("Is instance?", isinstance(self.service, QiskitRuntimeService))
        print("Account token: ", self.service._account.token)
        backend = self.service.backend('test_eagle_us-east')
        print("Backend:", backend)
        sampler = Sampler(backend)
        print("SAMPLER SERVICE:", sampler._service)
        print("Is instance Sampler?", isinstance(sampler._service, QiskitRuntimeService))   
        from qiskit import QuantumCircuit

        qc = QuantumCircuit(1)
        qc.measure_all()
        out1 = sampler.run([qc])
        out2 = sampler.run([qc])
        print("RUNTIME JOB ID 1:", out1.job_id())
        print("RUNTIME JOB ID 2:", out2.job_id())

        # print("GETTING ASSOCIATED ID:")
        # get_associated_runtime_job()
        return [out1.result(), out2.result()]

try:
    arguments = get_arguments()
except Exception:
    save_result(traceback.format_exc())
    raise

runner = Runner()
result = runner.run(arguments)
        
