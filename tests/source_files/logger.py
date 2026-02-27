import os
from time import sleep

from qiskit_serverless import get_logger, get_provider_logger

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
