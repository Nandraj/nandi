#!/usr/bin/env bash
# Nandi: start on http://localhost:8000 (API + built frontend). The first run sets everything up.
set -e
cd "$(dirname "$0")"
PORT="${NANDI_PORT:-8000}"

if ! backend/.venv/bin/python -c "import uvicorn" >/dev/null 2>&1; then
  echo "→ creating backend virtualenv (first run)…"
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install -q --upgrade pip
  backend/.venv/bin/pip install -q -r backend/requirements.txt
fi
[ -d frontend/dist ] || (echo "→ building the frontend (first run)…" && cd frontend && npm install && npm run build)
command -v ffmpeg >/dev/null || echo "⚠  ffmpeg not found: video joining will fail. Install it (macOS: brew install ffmpeg)."

URL="http://localhost:$PORT"
( sleep 2; { command -v open >/dev/null && open "$URL"; } || { command -v xdg-open >/dev/null && xdg-open "$URL"; } || true ) &
exec backend/.venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port "$PORT"
