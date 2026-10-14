#!/bin/bash

# Start local docker-compose environment with Fleets support.
# Detects docker-compose or podman-compose automatically.
#
# Usage:
#   bash gateway/examples/run_fleets_dev.sh

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# --- Detect container runtime ---
if command -v docker-compose &>/dev/null; then
    COMPOSE_CMD="docker-compose"
elif command -v docker &>/dev/null && docker compose version &>/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
elif command -v podman-compose &>/dev/null; then
    COMPOSE_CMD="podman-compose"
else
    echo "ERROR: No container compose tool found."
    echo "  Install one of: docker-compose, docker compose, or podman-compose"
    exit 1
fi

echo "=== Using: $COMPOSE_CMD ==="

# --- Setup environment ---
echo ""
echo "=== Setting up Fleets environment ==="
source gateway/examples/setup_fleets_env.sh

# --- Start services ---
echo ""
echo "=== Stopping services ==="
$COMPOSE_CMD -f docker-compose-dev.yaml down 2>/dev/null || true
echo "=== Starting services ==="
$COMPOSE_CMD -f docker-compose-dev.yaml up --build -d 2>&1 | cat

echo ""
echo "=== Waiting for services ==="
sleep 10

echo ""
echo "=== Service status ==="
$COMPOSE_CMD -f docker-compose-dev.yaml ps

echo ""
echo "=== Gateway logs (last 10 lines) ==="
$COMPOSE_CMD -f docker-compose-dev.yaml logs --tail=10 gateway

echo ""
echo "=== Health check ==="
curl -s http://localhost:8000/liveness || echo "Gateway not responding yet — wait a few more seconds"

echo ""
echo "=== Ready ==="
echo "Gateway: http://localhost:8000"
echo "To submit a Fleets job: python gateway/examples/submit_fleets_job.py"
