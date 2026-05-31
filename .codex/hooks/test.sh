#!/usr/bin/env bash
# Runs a scoped test against the file Claude just edited.
# PostToolUse hook for Edit|Write. Advisory only — always exits 0.
#
# Python: if a test file was edited, run just that file. If a source file under
# backend/app/ was edited, run the colocated backend/tests/unit/test_<name>.py
# when it exists.
# Frontend: `vitest related` runs only tests affected by the changed file.
set -u

FILE="$(jq -r '.tool_input.file_path // empty')"
[[ -z "$FILE" ]] && exit 0

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}"
[[ -d .venv/bin ]] && PATH="$PWD/.venv/bin:$PATH"

case "$FILE" in
  */backend/tests/*test_*.py)
    pytest -q "$FILE" 2>&1 | sed 's/^/[test] /' >&2
    ;;
  */backend/app/*.py)
    # Tests are flattened by basename under backend/tests/{unit,integration}/,
    # so map foo.py -> test_foo.py and run any matches pytest finds.
    NAME="$(basename "$FILE" .py)"
    MATCHES=()
    for D in backend/tests/unit backend/tests/integration; do
      [[ -f "$D/test_$NAME.py" ]] && MATCHES+=("$D/test_$NAME.py")
    done
    if (( ${#MATCHES[@]} > 0 )); then
      pytest -q "${MATCHES[@]}" 2>&1 | sed 's/^/[test] /' >&2
    fi
    ;;
  */frontend/src/*.ts|*/frontend/src/*.tsx)
    npm --prefix frontend exec -- vitest related --run "$FILE" 2>&1 | sed 's/^/[test] /' >&2
    ;;
esac
exit 0
