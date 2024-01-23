#!/usr/bin/env bash

set -eu -o pipefail
# set -x

DOCKER_BUILDKIT=${DOCKER_BUILDKIT:-'0'}


install_docker_buildx() {
  if ! docker buildx version > /dev/null 2>&1; then
    echo "Warning: Your pipeline needs to install the Docker buildx plugin"
    sudo apt-get update  -qq
    sudo apt-get install -qqy ca-certificates docker-buildx
  else
    echo "OK: Everything if fine! you can use the Docker buildx plugin"
  fi
}


main() {
  case ${DOCKER_BUILDKIT} in
    1) install_docker_buildx ;;
  esac
}


#
# ::main::
#
main
