#!/bin/sh
# Запуск сервиса: общие секреты для всех воркеров, очистка метрик, uvicorn.
set -e

gen_key() { python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"; }

if [ -z "$ENCRYPTION_KEY" ]; then
  echo '{"level":"WARNING","event":"ENCRYPTION_KEY not set, generated ephemeral key"}'
  ENCRYPTION_KEY=$(gen_key); export ENCRYPTION_KEY
fi
if [ -z "$TOKEN_SECRET" ]; then
  TOKEN_SECRET=$(gen_key); export TOKEN_SECRET
fi

WORKERS="${WORKERS:-4}"
if [ "${STORAGE_BACKEND:-memory}" != "redis" ] && [ "$WORKERS" != "1" ]; then
  echo '{"level":"WARNING","event":"memory storage requires a single worker, forcing WORKERS=1"}'
  WORKERS=1
fi

rm -rf "$PROMETHEUS_MULTIPROC_DIR" && mkdir -p "$PROMETHEUS_MULTIPROC_DIR"

exec uvicorn app.main:app \
  --host 0.0.0.0 --port 8000 \
  --workers "$WORKERS" \
  --loop uvloop --http httptools \
  --no-access-log \
  --backlog 4096 \
  --timeout-keep-alive 30
