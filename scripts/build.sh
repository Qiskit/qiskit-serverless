#!/usr/bin/env bash

set -euo pipefail

# shellcheck disable=SC2086
docker build $GATEWAY_DOCKER_BUILD_ARGS -f ./gateway/Dockerfile .
docker build $PROXY_DOCKER_BUILD_ARGS -f ./proxy/Dockerfile .
docker build $RAY_NODE_DOCKER_BUILD_ARGS -f Dockerfile-ray-node .
docker push "${GATEWAY_IMAGE}"
docker push "${PROXY_IMAGE}"
docker push "${RAY_NODE_IMAGE}"

DIGEST="$(docker inspect --format='{{index .RepoDigests 0}}' "${GATEWAY_IMAGE}" | awk -F@ '{print $2}')"
save_artifact gateway-image \
    type=image \
    "name=${GATEWAY_IMAGE}" \
    "digest=${DIGEST}" \
    "tags=${IMAGE_TAG}"

url="$(load_repo app-repo url)"
sha="$(load_repo app-repo commit)"

save_artifact gateway-image \
"source=${url}.git#${sha}"


DIGEST="$(docker inspect --format='{{index .RepoDigests 0}}' "${PROXY_IMAGE}" | awk -F@ '{print $2}')"
save_artifact proxy-image \
    type=image \
    "name=${PROXY_IMAGE}" \
    "digest=${DIGEST}" \
    "tags=${IMAGE_TAG}"

url="$(load_repo app-repo url)"
sha="$(load_repo app-repo commit)"

save_artifact proxy-image \
"source=${url}.git#${sha}"


DIGEST="$(docker inspect --format='{{index .RepoDigests 0}}' "${RAY_NODE_IMAGE}" | awk -F@ '{print $2}')"
save_artifact ray-node-image \
    type=image \
    "name=${RAY_NODE_IMAGE}" \
    "digest=${DIGEST}" \
    "tags=${IMAGE_TAG}"

url="$(load_repo app-repo url)"
sha="$(load_repo app-repo commit)"

save_artifact ray-node-image \
"source=${url}.git#${sha}"

# optional tags
#set +e
#TAG="$(cat /config/custom-image-tag)"
#set -e
#if [[ "${TAG}" ]]; then
#    #see build_setup script
#    IFS=',' read -ra tags <<< "${TAG}"
#    for i in "${!tags[@]}"
#    do
#        TEMP_TAG=${tags[i]}
#        TEMP_TAG=$(echo "$TEMP_TAG" | sed -e 's/^[[:space:]]*//')
#        echo "adding tag $i $TEMP_TAG"
#        ADDITIONAL_IMAGE_TAG="$ICR_REGISTRY_DOMAIN/$ICR_REGISTRY_NAMESPACE/$IMAGE_NAME:$TEMP_TAG"
#        docker tag "$IMAGE" "$ADDITIONAL_IMAGE_TAG"
#        docker push "$ADDITIONAL_IMAGE_TAG"
#
#        # save tags to pipelinectl
#        tags="$(load_artifact app-image tags)"
#        save_artifact app-image "tags=${tags},${TEMP_TAG}"
#    done
#fi

