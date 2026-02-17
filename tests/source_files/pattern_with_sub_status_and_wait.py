# source_files/program_4.py

from time import sleep
from qiskit_serverless import update_status, Job

print("==========")
print("update_status")
print(update_status(Job.MAPPING))
print("updated")
print("==========")

sleep(2)
