import os
from qiskit_serverless import QiskitFunction, ServerlessClient

serverless = ServerlessClient(
     token=os.environ.get("GATEWAY_TOKEN", "awesome_token"),
     host=os.environ.get("GATEWAY_HOST", "http://localhost:8000"),
)

help = """
title: custom-image-function
description: sample function implemented in a custom image
arguments:
     service: service created with the accunt information
     circuit: circuit
     observable: observable
"""

function_with_custom_image = QiskitFunction(
     title="custom-image-function",
     image="test_function:latest",
     provider=os.environ.get("PROVIDER_ID", "mockprovider"),
     description=help
)
serverless.upload(function_with_custom_image)

my_functions = serverless.list()
for function in my_functions:
     print("Name: " + function.title)
     print(function.description)
     print()

my_function = serverless.get("custom-image-function")
job = my_function.run(message="Argument for the custum function")

print(job.result())
print(job.logs())

jobs = my_function.get_jobs()
print(jobs)
