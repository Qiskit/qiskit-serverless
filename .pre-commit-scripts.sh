#!/bin/bash

set -e

cd "$(dirname "$0")"

run_black() {
    local dir="$1"
    echo "➡️  Running black in $dir..."
    cd "$dir"
    source venv/bin/activate
    tox -eblack
    cd - > /dev/null
}

run_lint() {
    local dir="$1"
    echo "➡️  Running lint in $dir..."
    cd "$dir"
    source venv/bin/activate
    tox -elint
    cd - > /dev/null
}

main() {
    local command="$1"
    shift

    if [ $# -eq 0 ]; then
        echo "Please provide at least one directory"
        exit 1
    fi

    case "$command" in
        black)
            for dir in "$@"; do
                run_black "$dir"
            done
            ;;
        lint)
            for dir in "$@"; do
                run_lint "$dir"
            done
            ;;
        *)
            echo "Unknown command: $command"
            echo "Usage: $0 {black|lint} <dir1> [dir2] [...]"
            exit 1
            ;;
    esac
}

main "$@"
