`a`\`/usr/bin/env bash

set -euo pipefail

if [[ "${PIPELINE_DEBUG:-0}" == 1 ]]; then
  set -x
  trap env EXIT
fi

get-icr-region() {
  case "$1" in
    ibm:sps-quantum:us-south)
      echo us
      ;;
    ibm:sps-quantum:us-east)
      echo us
      ;;
    ibm:sps-quantum:eu-de)
      echo de
      ;;
    ibm:sps-quantum:eu-gb)
      echo uk
      ;;
    ibm:sps-quantum:eu-es)
      echo es
      ;;
    ibm:sps-quantum:jp-tok)
      echo jp
      ;;
    ibm:sps-quantum:jp-osa)
      echo jp2
      ;;
    ibm:sps-quantum:au-syd)
      echo au
      ;;
    ibm:sps-quantum:br-sao)
      echo br
      ;;
    ibm:sps-quantum:eu-fr2)
      echo fr2
      ;;
    ibm:sps-quantum:ca-tor)
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

#IMAGE_NAME="$(get_env image-name "$(basename "$REPOSITORY" .git)")"
GATEWAY_IMAGE_NAME="$(get_env image-name "$(basename "$REPOSITORY" .git)")-gateway"
PROXY_IMAGE_NAME="$(get_env image-name "$(basename "$REPOSITORY" .git)")-proxy"
RAY_NODE__IMAGE_NAME="$(get_env image-name "$(basename "$REPOSITORY" .git)")-ray_node"
IMAGE_TAG="$(date +%Y%m%d%H%M%S)-$(cat /config/git-branch | tr -c '[:alnum:]_.-' '_')-$(cat /config/git-commit)"
IMAGE_TAG=${IMAGE_TAG////_}

# ICR_REGISTRY_NAMESPACE="$(cat /config/registry-namespace)"
ICR_REGISTRY_NAMESPACE="quantum-public"
ICR_REGISTRY_DOMAIN="$(get_env registry-domain "")"
if [ -z "$ICR_REGISTRY_DOMAIN" ]; then
  # Default to icr domain from registry-region
  ICR_REGISTRY_REGION="$(get-icr-region "$(cat /config/registry-region)")"
  ICR_REGISTRY_DOMAIN="$ICR_REGISTRY_REGION.icr.io"
fi
GATEWY_IMAGE="$ICR_REGISTRY_DOMAIN/$ICR_REGISTRY_NAMESPACE/$GATEWAY_IMAGE_NAME:$IMAGE_TAG"
PROXY_IMAGE="$ICR_REGISTRY_DOMAIN/$ICR_REGISTRY_NAMESPACE/$PROXY_IMAGE_NAME:$IMAGE_TAG"
RAY_NODE_IMAGE="$ICR_REGISTRY_DOMAIN/$ICR_REGISTRY_NAMESPACE/$RAY_NODEIMAGE_NAME:$IMAGE_TAG"
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

# shellcheck disable=SC2034 # next sourced script is using it where this script is also sourced
GATEWAY_DOCKER_BUILD_ARGS="-t $GATEWAY_IMAGE"
PROXY_DOCKER_BUILD_ARGS="-t $PROXY_IMAGE"
RAY_NODE_DOCKER_BUILD_ARGS="-t $RAY_NODE_IMAGE"
echo "end of build_setup"
echo $GATEWAY_IMAGE
echo $PROXY_IMAGE
echo $RAY_NODE_IMAGE
