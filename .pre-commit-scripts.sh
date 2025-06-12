#!/bin/bash

set -e

cd "$(dirname "$0")"

activate_venv() {
    local found_venv=$(find . -maxdepth 3 -name "activate")
    
    if [ -n "$found_venv" ]; then
        local venv_path=$(dirname "$(dirname "$found_venv")")
        local venv_folder=$(basename "$venv_path")
        source "$found_venv"
    else
        echo "❌ No virtual environment found"
        exit 1
    fi
}

run_black() {
    local dir="$1"
    echo "➡️  Running black in $dir..."
    cd "$dir"
    activate_venv
    tox -eblack
    cd - > /dev/null
}

run_lint() {
    local dir="$1"
    echo "➡️  Running lint in $dir..."
    cd "$dir"
    activate_venv
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