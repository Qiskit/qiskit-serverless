#!/usr/bin/env bash
set -euo pipefail

WORKTREE_PATH="${1:?Usage: create-worktree-hook.sh <worktree-path> <worktree-name>}"
WT_NAME="${2:?Usage: create-worktree-hook.sh <worktree-path> <worktree-name>}"

HOOKS_DIR="$(cd "$(dirname "$0")" && pwd)"

YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "  ${YELLOW}->  ${NC}Syncing .claude settings..."
"$HOOKS_DIR/copy-.claude-settings.sh" "$WORKTREE_PATH" "$WT_NAME"
echo

echo -e "  ${YELLOW}->  ${NC}Syncing .idea folders..."
"$HOOKS_DIR/copy-idea-folders.sh" "$WORKTREE_PATH" "$WT_NAME"
echo
