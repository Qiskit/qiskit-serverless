#! /bin/bash

set -e

# get new version
NEWNUM=$1
if [ -z "$NEWNUM" ]; then
    echo "Update quantum-serverless component versions."
    echo "Sample command:"
    echo "    update-version.sh 0.9.0"
    exit 0
fi

# derive additional tags
OLDTXT=$(git describe --tags $(git rev-list --tags --max-count=1))
OLDNUM="${OLDTXT:1}"

# commands need to be run from root directory
CURRDIR=$(pwd)
cd $(git rev-parse --show-toplevel)

###################################
# Helm
###################################

# update observability chart version
sed -i "s/version: ${OLDNUM}/version: ${NEWNUM}/" charts/qs-observability/Chart.yaml
sed -i "s/appVersion: \"${OLDNUM}\"/appVersion: \"${NEWNUM}\"/" charts/qs-observability/Chart.yaml

# update quantum-serverless chart versions
cd charts/quantum-serverless

sed -i "s/version: ${OLDNUM}/version: ${NEWNUM}/" Chart.yaml
sed -i "s/appVersion: \"${OLDNUM}\"/appVersion: \"${NEWNUM}\"/" Chart.yaml

sed -i "s/version: ${OLDNUM}/version: ${NEWNUM}/" charts/gateway/Chart.yaml
sed -i "s/appVersion: \"${OLDNUM}\"/appVersion: \"${NEWNUM}\"/" charts/gateway/Chart.yaml

sed -i "s/ray-node:${OLDNUM}/ray-node:${NEWNUM}/" charts/gateway/values.yaml

sed -i "s/version: ${OLDNUM}/version: ${NEWNUM}/" charts/jupyter/Chart.yaml
sed -i "s/appVersion: \"${OLDNUM}\"/appVersion: \"${NEWNUM}\"/" charts/jupyter/Chart.yaml

sed -i "s/version: ${OLDNUM}/version: ${NEWNUM}/" charts/repository/Chart.yaml
sed -i "s/appVersion: \"${OLDNUM}\"/appVersion: \"${NEWNUM}\"/" charts/repository/Chart.yaml

sed -i "s/tag: \"${OLDNUM}\"/tag: \"${NEWNUM}\"/" values.yaml
sed -i "s/tag: \"${OLDNUM}-py39\"/tag: \"${NEWNUM}-py39\"/" values.yaml
sed -i "s/ray-node:${OLDNUM}/ray-node:${NEWNUM}/" values.yaml
helm dependency update &>/dev/null
cd - &>/dev/null

###################################
# Client
###################################

sed -i "s/${OLDNUM}/${NEWNUM}/" client/quantum_serverless/VERSION.txt

###################################
# Compose
###################################

sed -i "s/VERSION:-${OLDNUM}/VERSION:-${NEWNUM}/g" docker-compose.yaml

###################################
# Docs
###################################

sed -i "s/${OLDNUM}/${NEWNUM}/g" docs/deployment/cloud.rst

cd "$CURRDIR"
