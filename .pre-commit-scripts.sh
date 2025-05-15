#!/bin/bash

set -e

cd "$(dirname "$0")"

run_gateway_black() {
    echo "➡️  Running black..."
    cd gateway
    source venv/bin/activate
    tox -eblack
    cd - > /dev/null
}

run_gateway_lint() {
    echo "➡️  Running lint..."
    cd gateway
    pwd
    source venv/bin/activate
    tox -elint
    cd - > /dev/null
}

main() {
    case "$1" in
        gateway_black) run_gateway_black ;;
        geteway_lint) run_gateway_lint ;;
        *)
            echo "Unknown command: $1"
            echo "Usage: $0 {gateway_black|geteway_lint|detect_secrets}"
            exit 1
        ;;
    esac
}

main "$@"
