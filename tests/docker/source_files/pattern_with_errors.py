# source_files/program_with_errors.py

from qiskit_serverless import get_arguments, save_result
from qiskit.primitives import StatevectorSampler as Sampler

# This is an intentional import error
from .circuit import wrong_circuit_import

print("This shouldn't execute")
