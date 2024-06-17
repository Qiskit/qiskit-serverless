#!/usr/bin/env bash

SCRIPT_NAME=$(basename $0)
echo "Running ${SCRIPT_NAME}"

cd gateway
pip install tox
pip install -r requirements.txt --no-cache-dir

tox -elint
tox -e py310
