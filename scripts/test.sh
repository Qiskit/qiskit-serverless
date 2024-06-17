#!/usr/bin/env bash

SCRIPT_NAME=$(basename $0)
echo "Running ${SCRIPT_NAME}"

cd gateway
tox -elint
tox -e py310
