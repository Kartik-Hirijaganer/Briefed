#!/usr/bin/env bash
# Runs a scoped type check against the file Claude just edited.
# PostToolUse hook for Edit|Write. Advisory only — always exits 0.
set -u

FILE="$(jq -r '.tool_input.file_path // empty')"
[[ -z "$FILE" ]] && exit 0

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}"
[[ -d .venv/bin ]] && PATH="$PWD/.venv/bin:$PATH"

case "$FILE" in
  */backend/*.py)
    mypy "$FILE" 2>&1 | sed 's/^/[typecheck] /' >&2
    ;;
  */frontend/src/*.ts|*/frontend/src/*.tsx)
    npm --prefix frontend exec -- tsc --noEmit 2>&1 | sed 's/^/[typecheck] /' >&2
    ;;
esac
exit 0
