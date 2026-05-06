#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

HOST="${DUEDATEHQ_DEPLOY_HOST:-ec2-3-89-24-84.compute-1.amazonaws.com}"
USER="${DUEDATEHQ_DEPLOY_USER:-scarlett}"
KEY="${DUEDATEHQ_DEPLOY_KEY:-$HOME/.ssh/id_ed25519_server}"
REMOTE_APP="${DUEDATEHQ_REMOTE_BACKEND:-/home/scarlett/duedatehq-demo/backend}"
PORT="${DUEDATEHQ_API_PORT:-8024}"
PUBLIC_PREFIX="${DUEDATEHQ_API_PUBLIC_PREFIX:-/demo-api/duedatehq/}"
NGINX_CONF="${DUEDATEHQ_NGINX_CONF:-/home/ec2-user/dify_demo_env/docker/nginx/conf.d/default.conf}"
HOST_GATEWAY="${DUEDATEHQ_NGINX_HOST_GATEWAY:-172.22.0.1}"

rsync -avz --delete \
  --exclude ".git" \
  --exclude ".env" \
  --exclude ".venv" \
  --exclude ".duedatehq" \
  --exclude ".logs" \
  --exclude ".pytest_cache" \
  --exclude "__pycache__" \
  --exclude "*.pyc" \
  --exclude "frontend/.vite" \
  --exclude "frontend/node_modules" \
  --exclude "frontend/dist" \
  --exclude "frontend/tsconfig.tsbuildinfo" \
  --exclude "src/duedatehq.egg-info" \
  -e "ssh -i $KEY -o StrictHostKeyChecking=accept-new" \
  "$ROOT_DIR/" \
  "$USER@$HOST:$REMOTE_APP/"

ssh -i "$KEY" -o StrictHostKeyChecking=accept-new "$USER@$HOST" \
  "REMOTE_APP='$REMOTE_APP' PORT='$PORT' PUBLIC_PREFIX='$PUBLIC_PREFIX' NGINX_CONF='$NGINX_CONF' HOST_GATEWAY='$HOST_GATEWAY' bash -s" <<'REMOTE'
set -euo pipefail

cd "$REMOTE_APP"
mkdir -p .logs .duedatehq

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required on the server to run the demo backend." >&2
  exit 1
fi

uv run --extra api python scripts/seed_small_demo.py >/tmp/duedatehq-seed.json

if [ -f .logs/duedatehq-api.pid ]; then
  old_pid="$(cat .logs/duedatehq-api.pid || true)"
  if [ -n "$old_pid" ] && kill -0 "$old_pid" >/dev/null 2>&1; then
    kill "$old_pid" || true
    sleep 1
  fi
fi

pkill -f "duedatehq.http_api:create_fastapi_app.*--port ${PORT}" >/dev/null 2>&1 || true

nohup uv run --extra api --extra agent uvicorn duedatehq.http_api:create_fastapi_app \
  --factory \
  --host 0.0.0.0 \
  --port "$PORT" \
  > .logs/duedatehq-api.log 2>&1 &
echo $! > .logs/duedatehq-api.pid

for attempt in $(seq 1 20); do
  if curl -fsS "http://127.0.0.1:${PORT}/flywheel/stats" >/tmp/duedatehq-health.json; then
    break
  fi
  if [ "$attempt" = "20" ]; then
    echo "DueDateHQ API did not become healthy." >&2
    tail -80 .logs/duedatehq-api.log >&2 || true
    exit 1
  fi
  sleep 1
done

python3 - "$NGINX_CONF" "$PUBLIC_PREFIX" "$HOST_GATEWAY" "$PORT" <<'PY'
from pathlib import Path
import sys

conf_path = Path(sys.argv[1])
public_prefix = sys.argv[2]
host_gateway = sys.argv[3]
port = sys.argv[4]

text = conf_path.read_text()
block = f"""
    location {public_prefix} {{
        proxy_pass http://{host_gateway}:{port}/;
        include proxy.conf;
    }}
"""

if f"location {public_prefix}" not in text:
    marker = "    location / {"
    if marker not in text:
        raise SystemExit(f"Could not find insertion marker in {conf_path}")
    text = text.replace(marker, block + "\n" + marker, 1)
    conf_path.write_text(text)
PY

sudo docker exec docker-nginx-1 nginx -t
sudo docker exec docker-nginx-1 nginx -s reload

curl -fsS -X POST "http://127.0.0.1:${PORT}/bootstrap/today" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"sarah-demo","session":{"session_id":"deploy-check"},"today":"2026-04-26"}' \
  >/tmp/duedatehq-bootstrap.json

echo "Backend deployed on port ${PORT}; nginx route ${PUBLIC_PREFIX}"
REMOTE

for attempt in $(seq 1 20); do
  if curl -fsS -X POST "https://naeu-demo.dify.dev${PUBLIC_PREFIX%/}/bootstrap/today" \
    -H "Content-Type: application/json" \
    -d '{"tenant_id":"2403c5e1-85ac-4593-86cc-02f8d97a8d92","session":{"session_id":"public-check"},"today":"2026-04-26"}' \
    >/tmp/duedatehq-public-bootstrap.json; then
    break
  fi
  if [ "$attempt" = "20" ]; then
    echo "Public API route did not become healthy." >&2
    exit 1
  fi
  sleep 1
done

echo "Deployed API: https://naeu-demo.dify.dev${PUBLIC_PREFIX}"
