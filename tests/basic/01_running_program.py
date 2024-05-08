#!/usr/bin/env python

from qiskit_serverless import ServerlessClient, QiskitFunction
import os


serverless = ServerlessClient(
    token=os.environ.get("GATEWAY_TOKEN", "awesome_token"),
    host=os.environ.get("GATEWAY_HOST", "http://localhost:8000"),
)
print(serverless)

pattern = QiskitFunction(
    title="my-first-pattern",
    entrypoint="pattern.py",
    working_dir="./source_files/",
)
serverless.upload(pattern)
job = serverless.run("my-first-pattern")
print(job)

print(job.result())
print(job.status())
print(job.logs())
