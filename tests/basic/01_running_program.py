#!/usr/bin/env python

from qiskit_serverless import ServerlessClient, QiskitFunction
import os


serverless = ServerlessClient(
    token=os.environ.get("GATEWAY_TOKEN", "awesome_token"),
    host=os.environ.get("GATEWAY_HOST", "http://localhost:8000"),
    instance=os.environ.get("GATEWAY_INSTANCE", "an_awesome_crn"),
)
print(serverless)

function = QiskitFunction(
    title="my-first-pattern",
    entrypoint="pattern.py",
    working_dir="./source_files/",
)
serverless.upload(function)

functions = {f.title: f for f in serverless.list()}
my_pattern_function = functions.get("my-first-pattern")
my_pattern_function

job = my_pattern_function.run()

print(job.result())
print(job.status())
print(job.logs())
