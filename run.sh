#!/usr/bin/env bash
# Starts both processes and stops them together on Ctrl-C.
set -euo pipefail
cd "$(dirname "$0")"
./.venv/bin/uvicorn api:app --app-dir src --port 8000 &
API=$!
trap 'kill $API 2>/dev/null || true' EXIT
cd web && npm run dev
