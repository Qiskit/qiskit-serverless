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

run_secrets() {
    echo "➡️  Running detect-secrets..."
    
    # Scan and update the baseline with any new secrets
    detect-secrets scan --update .secrets.baseline
    
    # Check for unaudited secrets
    UNAUDITED_COUNT=$(detect-secrets audit .secrets.baseline --report --json | jq '.stats.unaudited')
    
    if [ "$UNAUDITED_COUNT" -gt 0 ]; then
        echo "❌ $UNAUDITED_COUNT unaudited secrets detected. Please run \`detect-secrets audit .secrets.baseline\` to review."
        exit 1
    else
        echo "✅ No unaudited secrets found."
    fi
}


main() {
    case "$1" in
        gateway_black) run_gateway_black ;;
        geteway_lint) run_gateway_lint ;;
        detect_secrets) run_secrets ;;
        *)
            echo "Unknown command: $1"
            echo "Usage: $0 {gateway_black|geteway_lint|detect_secrets}"
            exit 1
        ;;
    esac
}

main "$@"
