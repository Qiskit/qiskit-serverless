#!/usr/bin/env bash

set -euo pipefail

if [[ "${PIPELINE_DEBUG:-0}" == 1 ]]; then
  set -x
  trap env EXIT
fi

get-icr-region() {
  case "$1" in
    ibm:yp:us-south)
      echo us
      ;;
    ibm:yp:us-east)
      echo us
      ;;
    ibm:yp:eu-de)
      echo de
      ;;
    ibm:yp:eu-gb)
      echo uk
      ;;
    ibm:yp:eu-es)
      echo es
      ;;
    ibm:yp:jp-tok)
      echo jp
      ;;
    ibm:yp:jp-osa)
      echo jp2
      ;;
    ibm:yp:au-syd)
      echo au
      ;;
    ibm:yp:br-sao)
      echo br
      ;;
    ibm:yp:eu-fr2)
      echo fr2
      ;;
    ibm:yp:ca-tor)
      echo ca
      ;;
    stg)
      echo stg
      ;;  
    *)
      echo "Unknown region: $1" >&2
      exit 1
      ;;
  esac
}

# curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -
# add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"
# apt-get update && apt-get install docker-ce-cli

find /config

IBMCLOUD_API=$(get_env ibmcloud-api "https://cloud.ibm.com")

if [[ -s "/config/repository" ]]; then
  REPOSITORY="$(cat /config/repository)"
else
  REPOSITORY="$(load_repo app-repo url)"
fi

IMAGE_NAME="$(get_env image-name "$(basename "$REPOSITORY" .git)")"
IMAGE_TAG="$(date +%Y%m%d%H%M%S)-$(cat /config/git-branch | tr -c '[:alnum:]_.-' '_')-$(cat /config/git-commit)"
IMAGE_TAG=${IMAGE_TAG////_}

if [[ -f "/config/break_glass" ]]; then
  ARTIFACTORY_URL="$(jq -r .parameters.repository_url /config/artifactory)"
  ARTIFACTORY_REGISTRY="$(sed -E 's~https://(.*)/?~\1~' <<<"$ARTIFACTORY_URL")"
  ARTIFACTORY_INTEGRATION_ID="$(jq -r .instance_id /config/artifactory)"
  IMAGE="$ARTIFACTORY_REGISTRY/$IMAGE_NAME:$IMAGE_TAG"
  jq -j --arg instance_id "$ARTIFACTORY_INTEGRATION_ID" '.services[] | select(.instance_id == $instance_id) | .parameters.token' /toolchain/toolchain.json | docker login -u "$(jq -r '.parameters.user_id' /config/artifactory)" --password-stdin "$(jq -r '.parameters.repository_url' /config/artifactory)"
else
  # ICR_REGISTRY_NAMESPACE="$(cat /config/registry-namespace)"
  ICR_REGISTRY_NAMESPACE="quantum-public"
  ICR_REGISTRY_DOMAIN="$(get_env registry-domain "")"
  if [ -z "$ICR_REGISTRY_DOMAIN" ]; then
    # Default to icr domain from registry-region
    ICR_REGISTRY_REGION="$(get-icr-region "$(cat /config/registry-region)")"
    ICR_REGISTRY_DOMAIN="$ICR_REGISTRY_REGION.icr.io"
  fi
  IMAGE="$ICR_REGISTRY_DOMAIN/$ICR_REGISTRY_NAMESPACE/$IMAGE_NAME:$IMAGE_TAG"
  docker login -u iamapikey --password-stdin "$ICR_REGISTRY_DOMAIN" < /config/api-key

  # Create the namespace if needed to ensure the push will be can be successfull
  echo "Checking registry namespace: ${ICR_REGISTRY_NAMESPACE}"
  IBM_LOGIN_REGISTRY_REGION=$(< /config/registry-region awk -F: '{print $3}')
  ibmcloud config --check-version false
  ibmcloud login --apikey @/config/api-key -r "$IBM_LOGIN_REGISTRY_REGION" -a "$IBMCLOUD_API"
  NS=$( ibmcloud cr namespaces | sed 's/ *$//' | grep -x "${ICR_REGISTRY_NAMESPACE}" ||: )

  if [ -z "${NS}" ]; then
      echo "Registry namespace ${ICR_REGISTRY_NAMESPACE} not found"
      ibmcloud cr namespace-add "${ICR_REGISTRY_NAMESPACE}"
      echo "Registry namespace ${ICR_REGISTRY_NAMESPACE} created."
  else
      echo "Registry namespace ${ICR_REGISTRY_NAMESPACE} found."
  fi
fi

# shellcheck disable=SC2034 # next sourced script is using it where this script is also sourced
DOCKER_BUILD_ARGS="-t $IMAGE"
echo "end of build_setup"
echo $IMAGE
