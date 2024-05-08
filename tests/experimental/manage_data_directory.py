#!/usr/bin/env python

import os
from qiskit_serverless import ServerlessClient, QiskitFunction

serverless = ServerlessClient(
    token=os.environ.get("GATEWAY_TOKEN", "awesome_token"),
    host=os.environ.get("GATEWAY_HOST", "http://localhost:8000"),
)
print(serverless)

import tarfile

filename= "uploaded_file.tar"
file= tarfile.open(filename,"w")
file.add("manage_data_directory.py")
file.close()

serverless.file_upload(filename)

function = QiskitFunction(
    title="file-producer", entrypoint="produce_files.py", working_dir="./source_files/"
)

serverless.upload(function)
job = serverless.run("file-producer")
print(job)
print(job.result())
print(job.status())
print(job.logs())


print(serverless.files())

function = QiskitFunction(
    title="file-consumer", entrypoint="consume_files.py", working_dir="./source_files/"
)

serverless.upload(function)
job = serverless.run("file-consumer")
print(job)
print(job.result())
print(job.status())
print(job.logs())

print(serverless.files())

serverless.file_delete("uploaded_file.tar")

print("Done deleting files")
