#!/usr/bin/env python

import os
from qiskit_serverless import ServerlessClient
from qiskit_serverless import QiskitFunction

serverless = ServerlessClient(
    token=os.environ.get("GATEWAY_TOKEN", "awesome_token"),
    instance=os.environ.get("GATEWAY_INSTANCE", "awesome_crn"),
    host=os.environ.get("GATEWAY_HOST", "http://localhost:8000"),
)

function = QiskitFunction(
    title="test-runtime-wrapper",
    entrypoint="pattern_with_runtime_wrapper.py",
    working_dir="./source_files/",
)
serverless.upload(function)

functions = {f.title: f for f in serverless.list()}
my_pattern_function = functions.get("test-runtime-wrapper")

job = my_pattern_function.run()
job_id = job.job_id
print("Serverless job id", job_id)

print(serverless.runtime_jobs(job_id))

