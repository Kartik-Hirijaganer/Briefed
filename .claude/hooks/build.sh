#!/usr/bin/env bash
# Runs the frontend build when Claude edits a frontend file.
# PostToolUse hook for Edit|Write. Advisory only — always exits 0.
# No-op for Python edits: this repo has no Python build step.
set -u

FILE="$(jq -r '.tool_input.file_path // empty')"
[[ -z "$FILE" ]] && exit 0

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}"
[[ -d .venv/bin ]] && PATH="$PWD/.venv/bin:$PATH"

case "$FILE" in
  */frontend/src/*|*/frontend/*.json|*/frontend/*.ts|*/frontend/*.tsx|*/frontend/vite.config.*)
    npm --prefix frontend run build 2>&1 | sed 's/^/[build] /' >&2
    ;;
esac
exit 0
