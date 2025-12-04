from qiskit_serverless import get_logger, get_provider_logger

user_logger = get_logger()
provider_logger = get_provider_logger()

user_logger.info("User log")
user_logger.warning("User log")
user_logger.error("User log")

provider_logger.info("Provider log")
provider_logger.warning("Provider log")
provider_logger.error("Provider log")