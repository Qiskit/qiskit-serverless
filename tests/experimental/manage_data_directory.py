#!/usr/bin/env python

import os
from qiskit_serverless import ServerlessClient, QiskitFunction

serverless = ServerlessClient(
    token=os.environ.get("GATEWAY_TOKEN", "awesome_token"),
    host=os.environ.get("GATEWAY_HOST", "http://localhost:8000"),
)
print(serverless)

function = QiskitFunction(
    title="file-producer", entrypoint="produce_files.py", working_dir="./source_files/"
)
serverless.upload(function)

import tarfile

filename = "uploaded_file.tar"
file = tarfile.open(filename, "w")
file.add("manage_data_directory.py")
file.close()

serverless.file_upload(filename, function)

functions = {f.title: f for f in serverless.list()}
file_producer_function = functions.get("file-producer")
file_producer_function
job = file_producer_function.run()
print(job)
print(job.result())
print(job.status())
print(job.logs())


print(serverless.files(file_producer_function))

function = QiskitFunction(
    title="file-consumer", entrypoint="consume_files.py", working_dir="./source_files/"
)
serverless.upload(function)

functions = {f.title: f for f in serverless.list()}
file_consumer_function = functions.get("file-consumer")
file_consumer_function
job = file_consumer_function.run()
print(job)
print(job.result())
print(job.status())
print(job.logs())

print(serverless.files(file_consumer_function))

serverless.file_delete("uploaded_file.tar", file_consumer_function)

print("Done deleting files")
