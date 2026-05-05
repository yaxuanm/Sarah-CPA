#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"

HOST="${DUEDATEHQ_DEPLOY_HOST:-ec2-3-89-24-84.compute-1.amazonaws.com}"
USER="${DUEDATEHQ_DEPLOY_USER:-scarlett}"
KEY="${DUEDATEHQ_DEPLOY_KEY:-$HOME/.ssh/id_ed25519_server}"
REMOTE_STAGING="${DUEDATEHQ_REMOTE_STAGING:-/home/scarlett/duedatehq-demo/frontend-dist}"
REMOTE_WEBROOT="${DUEDATEHQ_REMOTE_WEBROOT:-/home/ec2-user/dify_demo_env/docker/volumes/certbot/www/duedatehq}"
PUBLIC_BASE="${DUEDATEHQ_PUBLIC_BASE:-/duedatehq/}"
API_BASE="${VITE_DUEDATEHQ_API_BASE:-/demo-api/duedatehq}"

cd "$FRONTEND_DIR"
VITE_DUEDATEHQ_API_BASE="$API_BASE" npm run build -- --base="$PUBLIC_BASE"
cp "$ROOT_DIR/demo-day-deck.html" "$FRONTEND_DIR/dist/demo-day-deck.html"
cp "$ROOT_DIR/due-datehq-ten-minute-story-compact.html" "$FRONTEND_DIR/dist/due-datehq-ten-minute-story-compact.html"

rsync -avz --delete \
  -e "ssh -i $KEY -o StrictHostKeyChecking=accept-new" \
  "$FRONTEND_DIR/dist/" \
  "$USER@$HOST:$REMOTE_STAGING/"

ssh -i "$KEY" -o StrictHostKeyChecking=accept-new "$USER@$HOST" \
  "sudo mkdir -p '$REMOTE_WEBROOT' && sudo rsync -a --delete '$REMOTE_STAGING/' '$REMOTE_WEBROOT/' && sudo docker exec docker-nginx-1 nginx -s reload"

echo "Deployed: https://naeu-demo.dify.dev${PUBLIC_BASE}"
