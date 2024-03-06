#!/usr/bin/env python

from quantum_serverless import ServerlessProvider, QiskitPattern
import os


serverless = ServerlessProvider(
    token=os.environ.get("GATEWAY_TOKEN", "awesome_token"),
    host=os.environ.get("GATEWAY_HOST", "http://localhost:8000"),
)
print(serverless)

pattern = QiskitPattern(
    title="my-first-pattern", entrypoint="pattern.py", working_dir="./source_files/"
)
serverless.upload(pattern)
job = serverless.run("my-first-pattern")
print(job)

print(job.result())
print(job.status())
print(job.logs())
