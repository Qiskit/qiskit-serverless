#!/bin/bash

# Fresh deploy and run fleets integration tests.
# Tears down any existing containers, rebuilds, waits for readiness,
# then runs the pytest suite in tests/fleets/.
#
# Usage:
#   bash gateway/examples/run_fleets_integration_test.sh

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# Detect compose tool
if command -v docker-compose &>/dev/null; then
    COMPOSE_CMD="docker-compose"
elif command -v docker &>/dev/null && docker compose version &>/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
elif command -v podman-compose &>/dev/null; then
    COMPOSE_CMD="podman-compose"
else
    echo "ERROR: No container compose tool found."
    exit 1
fi

COMPOSE_FILE="docker-compose-fleets-test.yaml"

echo "=== Using: $COMPOSE_CMD ==="
echo "=== Compose file: $COMPOSE_FILE ==="

# --- Tear down existing ---
# NOTE: scoped to this compose project only. Do NOT add --remove-orphans:
# under podman-compose it removes containers from OTHER projects sharing the
# host, which has destroyed unrelated dev stacks. `down -v` only affects the
# services and named volumes declared in this file.
echo ""
echo "=== Tearing down existing containers ==="
$COMPOSE_CMD -f "$COMPOSE_FILE" down -v 2>/dev/null || true
# Also stop any containers from the dev compose file that may conflict
$COMPOSE_CMD -f docker-compose-dev.yaml down 2>/dev/null || true

# --- Build the fleet-node base image first ---
# The fleet-worker is FROM fleet-node:latest, and `compose up --build` does NOT
# build a FROM-referenced base, so build it here (tagged fleet-node:latest).
if command -v docker &>/dev/null; then
    BUILD_CMD="docker build"
elif command -v podman &>/dev/null; then
    BUILD_CMD="podman build"
else
    echo "ERROR: no docker/podman found to build the fleet-node base image."
    exit 1
fi
echo ""
echo "=== Building fleet-node base image ==="
$BUILD_CMD -t fleet-node:latest -f fleet-node/Dockerfile .

# --- Build and start ---
echo ""
echo "=== Building and starting services ==="
$COMPOSE_CMD -f "$COMPOSE_FILE" up --build -d 2>&1 | cat

# --- Wait for gateway readiness ---
echo ""
echo "=== Waiting for gateway to be ready ==="
TIMEOUT=60
ELAPSED=0
until curl -s http://localhost:8000/liveness >/dev/null 2>&1; do
    sleep 2
    ELAPSED=$((ELAPSED + 2))
    if [ $ELAPSED -ge $TIMEOUT ]; then
        echo "ERROR: Gateway not ready after ${TIMEOUT}s"
        $COMPOSE_CMD -f "$COMPOSE_FILE" logs gateway | tail -30
        exit 1
    fi
done
echo "Gateway ready (${ELAPSED}s)"

# --- Wait for MinIO readiness ---
echo ""
echo "=== Waiting for MinIO ==="
ELAPSED=0
until curl -s http://localhost:9000/minio/health/live >/dev/null 2>&1; do
    sleep 1
    ELAPSED=$((ELAPSED + 1))
    if [ $ELAPSED -ge 30 ]; then
        echo "ERROR: MinIO not ready after 30s"
        exit 1
    fi
done
echo "MinIO ready"

# --- Run tests ---
echo ""
echo "=== Running fleets integration tests ==="
cd "$REPO_ROOT"

PYTHON="${REPO_ROOT}/gateway/.tox/shared/bin/python"
PIP="${REPO_ROOT}/gateway/.tox/shared/bin/pip"
if [ ! -f "$PYTHON" ]; then
    echo "ERROR: gateway tox env not found. Run: cd gateway && tox -e shared --notest"
    exit 1
fi

# Ensure integration test dependencies are installed
"$PIP" install -q boto3 psycopg2-binary 2>/dev/null
# Ensure client SDK is installed
if ! "$PYTHON" -c "import qiskit_serverless" 2>/dev/null; then
    "$PIP" install -q -e "${REPO_ROOT}/client/"
fi

export GATEWAY_HOST="http://localhost:8000"
export GATEWAY_TOKEN="awesome_token"
export DATABASE_HOST="localhost"
export DATABASE_PORT="5432"
export DATABASE_NAME="serverlessdb"
export DATABASE_USER="serverlessuser"
export DATABASE_PASSWORD="serverlesspassword"
export MINIO_ENDPOINT="http://localhost:9000"
export MINIO_ACCESS_KEY="minioadmin"
export MINIO_SECRET_KEY="minioadmin"

"$PYTHON" -m pytest tests/fleets/ -v --tb=short "$@"
TEST_EXIT=$?

# --- Summary ---
echo ""
if [ $TEST_EXIT -eq 0 ]; then
    echo "=== ALL TESTS PASSED ==="
else
    echo "=== TESTS FAILED (exit code: $TEST_EXIT) ==="
    echo ""
    echo "=== Gateway logs (last 20 lines) ==="
    $COMPOSE_CMD -f "$COMPOSE_FILE" logs --tail=20 gateway
    echo ""
    echo "=== Scheduler logs (last 20 lines) ==="
    $COMPOSE_CMD -f "$COMPOSE_FILE" logs --tail=20 scheduler
    echo ""
    echo "=== Fleet-worker logs (last 20 lines) ==="
    $COMPOSE_CMD -f "$COMPOSE_FILE" logs --tail=20 fleet-worker
fi

exit $TEST_EXIT
