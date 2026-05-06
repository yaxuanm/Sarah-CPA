#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"

echo "==> Backend contract checks"
cd "$ROOT_DIR"
uv run --extra api --with pytest --with httpx pytest \
  tests/test_smoke.py \
  tests/test_http_api.py \
  -q

echo "==> Frontend dependency check"
cd "$FRONTEND_DIR"
if [ ! -d node_modules ]; then
  npm ci
fi

echo "==> Frontend build"
npm run build

echo "==> Frontend render-spec smoke"
npm run test:render-spec

echo "==> Build checks passed"
