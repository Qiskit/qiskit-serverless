#!/usr/bin/env bash

SCRIPT_NAME=$(basename $0)
echo "Running ${SCRIPT_NAME}"

cd gateway

#yum install -y python3.10
#yum install -y python3-pip
#ln -s /usr/bin/python3.10 /usr/bin/python
#pip3 install --upgrade pip
#ln /usr/bin/pip3 /usr/bin/pip
#pip install tox
#pip install -r requirements.txt --no-cache-dir

tox -elint
tox -epy310
