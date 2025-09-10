#!/usr/bin/env bash
set -e
set -o pipefail

# Simplified startup for Render - avoid SocketIO import issues
# 1) Apply DB migrations (disable eventlet in CLI)
# 2) Start Gunicorn with sync worker directly on wsgi_simple

# Defaults
export USE_EVENTLET=0
export USE_EVENTLET_FOR_SERVER=0
export WORKERS=${WORKERS:-1}
export PORT=${PORT:-10000}
export FLASK_APP=app

echo "[start_render_simple] Applying database migrations..."
if ! python run_migrations.py; then
  echo "[start_render_simple] WARNING: run_migrations.py failed; trying flask db upgrade..."
  if ! python -m flask db upgrade heads; then
    echo "[start_render_simple] WARNING: both migration methods failed; continuing anyway"
  fi
fi

echo "[start_render_simple] Running DB consistency fixes (best-effort)..."
python scripts/fix_db_consistency.py || echo "[start_render_simple] fix_db_consistency skipped/failed"
python scripts/ensure_draft_orders_columns.py || echo "[start_render_simple] ensure_draft_orders_columns skipped/failed"

echo "[start_render_simple] Creating/ensuring admin user (best-effort)..."
python create_user.py || echo "[start_render_simple] create_user.py skipped/failed"

echo "[start_render_simple] Starting Gunicorn (sync worker, no SocketIO)..."
exec gunicorn --worker-class sync --workers ${WORKERS} -b 0.0.0.0:${PORT} wsgi_simple:application
