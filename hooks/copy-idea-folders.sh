#!/usr/bin/env bash
set -euo pipefail

WORKTREE_PATH="${1:?Usage: copy-idea-folders.sh <worktree-path> <worktree-name>}"
WT_NAME="${2:?Usage: copy-idea-folders.sh <worktree-path> <worktree-name>}"

GREEN='\033[0;32m'
CYAN='\033[0;36m'
DIM='\033[2m'
NC='\033[0m'

main_wt=$(git worktree list 2>/dev/null | head -1 | awk '{print $1}')
[ -n "$main_wt" ] || { echo "No es un repositorio git" >&2; exit 1; }
[ "$WORKTREE_PATH" != "$main_wt" ] || exit 0

copied=0
for dir in .run .idea; do
    for src in "$main_wt/$dir" "$main_wt"/*/"$dir"; do
        [ -d "$src" ] || continue
        rel="${src#$main_wt/}"
        dst="$WORKTREE_PATH/$rel"
        mkdir -p "$dst"
        cp -r "$src/." "$dst/" 2>/dev/null || true
        echo -e "  ${GREEN}✓${NC} $rel"
        copied=$((copied+1))
    done
done

idea_name_file="$WORKTREE_PATH/.idea/.name"
if [[ -f "$idea_name_file" ]]; then
    base_name=$(cat "$idea_name_file")
    printf '%s:%s' "$base_name" "$WT_NAME" > "$idea_name_file"
    echo -e "  ${GREEN}✓${NC} .idea/.name: ${CYAN}${base_name}:${WT_NAME}${NC}"
fi

[ "$copied" -eq 0 ] && echo -e "  ${DIM}(no .idea/.run changes)${NC}"
