#!/usr/bin/env python

from qiskit_serverless import QiskitFunction

function = QiskitFunction(
    title="pattern-with-dependencies",
    entrypoint="pattern_with_dependencies.py",
    working_dir="./source_files/",
    dependencies=["pendulum"],
)

from qiskit_serverless import ServerlessClient
import os

serverless = ServerlessClient(
    token=os.environ.get("GATEWAY_TOKEN", "awesome_token"),
    host=os.environ.get("GATEWAY_HOST", "http://localhost:8000"),
    instance=os.environ.get("GATEWAY_INSTANCE", "an_awesome_crn"),
)
print(serverless)

serverless.upload(function)

functions = {f.title: f for f in serverless.list()}
my_pattern_function = functions.get("pattern-with-dependencies")
my_pattern_function

job = my_pattern_function.run()
print(job)

print(job.result())
print(job.status())
print(job.logs())
