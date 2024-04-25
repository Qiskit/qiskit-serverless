"""Default entrypoint."""

import os
import sys

from quantum_serverless import get_arguments, save_result

sys.path.append({{mount_path}})

from {{package_name}} import Runner

arguments = get_arguments()

runner = Runner()
result = runner.main(arguments)

save_result(result)
