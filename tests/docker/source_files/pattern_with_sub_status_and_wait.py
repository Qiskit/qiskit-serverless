# source_files/program_4.py

from time import sleep
from qiskit_serverless import update_status, Job

# this is weird, we have to fix this.
# The status is not "Running" at the very beggining,
# we cannot update the status because it is "Initializing/Pending"
sleep(1)

print("==========")

print("update_status")
print(update_status(Job.MAPPING))
print("updated")
print("==========")

sleep(3)
