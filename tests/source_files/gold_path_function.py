# source_files/program_3.py

import os
from time import sleep

from qiskit_serverless import get_arguments, save_result

from qiskit.primitives import StatevectorSampler as Sampler

from qiskit_serverless import get_logger, get_provider_logger

# get all arguments passed to this program
arguments = get_arguments()

# get specific argument that we are interested in
circuit = arguments.get("circuit")

sampler = Sampler()

quasi_dists = sampler.run([circuit]).result()[0].data.meas.get_counts()

print(f"Quasi distribution: {quasi_dists}")

user_logger = get_logger()
provider_logger = get_provider_logger()

get_logger().info("User log")
user_logger.info("User multiline\nlog")
user_logger.warning("User log")
user_logger.error("User log")

print("DELAY STARTS")
delay = int(os.environ.get("DELAY", "10"))
sleep(delay)

get_provider_logger().info("Provider log")
provider_logger.info("Provider multiline\nlog")
provider_logger.warning("Provider log")
provider_logger.error("Provider log")

# saving results of a program
save_result({"quasi_dists": quasi_dists})
