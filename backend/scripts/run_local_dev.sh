#!/usr/bin/env bash
set -euo pipefail

api_host="${BRIEFED_API_HOST:-127.0.0.1}"
api_port="${BRIEFED_API_PORT:-8000}"
frontend_host="${BRIEFED_FRONTEND_HOST:-127.0.0.1}"
frontend_port="${BRIEFED_FRONTEND_PORT:-5173}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
python_bin="${BRIEFED_PYTHON:-${repo_root}/.venv/bin/python}"

if [ ! -x "${python_bin}" ]; then
  python_bin="python3"
fi

terminate_pids() {
  local label="$1"
  local pids="$2"
  local remaining
  if [ -z "${pids// }" ]; then
    return 0
  fi
  echo "==> Stopping ${label}: ${pids}"
  # shellcheck disable=SC2086
  kill -TERM ${pids} 2>/dev/null || true
  for _ in {1..30}; do
    sleep 0.2
    remaining=""
    for pid in ${pids}; do
      if kill -0 "${pid}" 2>/dev/null; then
        remaining="${remaining} ${pid}"
      fi
    done
    if [ -z "${remaining// }" ]; then
      return 0
    fi
  done
  echo "==> Force stopping ${label}:${remaining}"
  # shellcheck disable=SC2086
  kill -KILL ${remaining} 2>/dev/null || true
}

free_port() {
  local port="$1"
  local pids
  if ! command -v lsof >/dev/null 2>&1; then
    echo "==> lsof is unavailable; cannot pre-free localhost port ${port}"
    return 0
  fi
  pids="$(lsof -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null | tr '\n' ' ' || true)"
  terminate_pids "localhost port ${port}" "${pids}"
}

free_previous_dev_processes() {
  local pids
  if ! command -v pgrep >/dev/null 2>&1; then
    return 0
  fi
  pids="$(pgrep -f "backend/scripts/local_sqs_worker.py" 2>/dev/null | tr '\n' ' ' || true)"
  terminate_pids "previous local SQS worker" "${pids}"
  pids="$(pgrep -f "${repo_root}/node_modules/.bin/vite" 2>/dev/null | tr '\n' ' ' || true)"
  terminate_pids "previous local Vite server" "${pids}"
}

child_pids=()

cleanup() {
  local pids
  pids="${child_pids[*]:-}"
  terminate_pids "local dev process group" "${pids}"
}

trap cleanup EXIT INT TERM

free_port "${api_port}"
free_port "${frontend_port}"
free_previous_dev_processes

echo "==> Starting API on http://${api_host}:${api_port}"
"${python_bin}" -m uvicorn app.main:app \
  --app-dir backend \
  --reload \
  --host "${api_host}" \
  --port "${api_port}" &
child_pids+=("$!")

echo "==> Starting LocalStack SQS worker"
"${python_bin}" backend/scripts/local_sqs_worker.py &
child_pids+=("$!")

if [ -f package-lock.json ]; then
  echo "==> Starting frontend on http://${frontend_host}:${frontend_port}"
  npm --workspace frontend run dev -- \
    --host "${frontend_host}" \
    --port "${frontend_port}" \
    --strictPort &
  child_pids+=("$!")
fi

while true; do
  for pid in "${child_pids[@]}"; do
    if ! kill -0 "${pid}" 2>/dev/null; then
      set +e
      wait "${pid}"
      status="$?"
      set -e
      if [ "${status}" -eq 0 ]; then
        echo "local dev process ${pid} exited"
      else
        echo "local dev process ${pid} failed with exit status ${status}"
      fi
      exit "${status}"
    fi
  done
  sleep 1
done
