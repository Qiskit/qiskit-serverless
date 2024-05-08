#!/usr/bin/env python

from qiskit_serverless import ServerlessClient
import os

serverless = ServerlessClient(
    token=os.environ.get("GATEWAY_TOKEN", "awesome_token"),
    host=os.environ.get("GATEWAY_HOST", "http://localhost:8000"),
)
print(serverless)

from qiskit_serverless import QiskitFunction

pattern = QiskitFunction(
    title="pattern-to-fetch-results", entrypoint="pattern.py", working_dir="./source_files/"
)
serverless.upload(pattern)

job1 = serverless.run("pattern-to-fetch-results")
job2 = serverless.run("pattern-to-fetch-results")
print(job1)
print(job2)

job_id1 = job1.job_id
job_id2 = job2.job_id

print(job1.result())
print(job2.result())


retrieved_job1 = serverless.get_job_by_id(job_id1)
retrieved_job2 = serverless.get_job_by_id(job_id2)


print(f"Job 1 results: {retrieved_job1.result()}")
print(f"Job 2 results: {retrieved_job2.result()}")

print(f"Job 1 logs: {retrieved_job1.logs()}")

print(serverless.get_jobs(limit=2, offset=1))
