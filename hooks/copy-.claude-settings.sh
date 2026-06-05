#!/usr/bin/env bash
set -euo pipefail

WORKTREE_PATH="${1:?Usage: copy-.claude-settings.sh <worktree-path> <worktree-name>}"
: "${2:?Usage: copy-.claude-settings.sh <worktree-path> <worktree-name>}"

GREEN='\033[0;32m'
DIM='\033[2m'
NC='\033[0m'

main_wt=$(git worktree list 2>/dev/null | head -1 | awk '{print $1}')
[ -n "$main_wt" ] || { echo "No es un repositorio git" >&2; exit 1; }
[ "$WORKTREE_PATH" != "$main_wt" ] || exit 0

items=(settings.json settings.local.json CLAUDE.md RTK.md hooks commands agents skills memory plugins)
copied=0
for item in "${items[@]}"; do
    src="$main_wt/.claude/$item"
    [ -e "$src" ] || continue
    if [ -f "$src" ]; then
        dst="$WORKTREE_PATH/.claude/$item"
        if [ ! -e "$dst" ]; then
            mkdir -p "$WORKTREE_PATH/.claude"
            cp "$src" "$dst"
            echo -e "  ${GREEN}✓${NC} .claude/$item"
            copied=$((copied+1))
        fi
    elif [ -d "$src" ]; then
        while IFS= read -r f; do
            rel="${f#$main_wt/.claude/}"
            dst="$WORKTREE_PATH/.claude/$rel"
            if [ ! -e "$dst" ]; then
                mkdir -p "$(dirname "$dst")"
                cp "$f" "$dst"
                echo -e "  ${GREEN}✓${NC} .claude/$rel"
                copied=$((copied+1))
            fi
        done < <(find "$src" -type f)
    fi
done

[ "$copied" -eq 0 ] && echo -e "  ${DIM}(no .claude changes)${NC}"
