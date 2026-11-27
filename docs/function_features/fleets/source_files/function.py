"""Example entrypoint for the Fleets tutorial."""

from qiskit_serverless import get_arguments, get_logger, save_result

# get_logger() emits the [PUBLIC] tag the Fleets wrapper routes to the job's
# user-visible log; plain print() also works and is always user-visible.
logger = get_logger()

arguments = get_arguments()
name = arguments.get("name", "world")

logger.info("Running function... name=%s", name)
save_result({"greeting": f"Hello, {name}!"})
logger.info("Completed running function.")
