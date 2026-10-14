#!/bin/bash
# Run the Fleets integration test with the correct Python environment.
#
# Usage:
#   bash examples/test_fleets.sh              # run all scenarios
#   bash examples/test_fleets.sh custom       # custom function only
#   bash examples/test_fleets.sh provider     # provider function only

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

set +e
source gateway/examples/setup_fleets_env.sh
SOURCE_RC=$?
set -e
if [ $SOURCE_RC -ne 0 ]; then
    exit $SOURCE_RC
fi

PYTHON="${REPO_ROOT}/gateway/.tox/shared/bin/python"
PIP="${REPO_ROOT}/gateway/.tox/shared/bin/pip"

if [ ! -f "$PYTHON" ]; then
    echo "ERROR: gateway tox env not found."
    echo "  Run: cd gateway && tox -e shared --notest"
    exit 1
fi

# Ensure client SDK is installed
if ! "$PYTHON" -c "import qiskit_serverless" 2>/dev/null; then
    echo "Installing client SDK into tox env..."
    "$PIP" install -e "${REPO_ROOT}/client/" -q
fi

if [ $# -gt 0 ]; then
    exec "$PYTHON" gateway/examples/submit_fleets_job.py "$@"
fi

"$PYTHON" gateway/examples/submit_fleets_job.py custom || exit 1
"$PYTHON" gateway/examples/submit_fleets_job.py provider
