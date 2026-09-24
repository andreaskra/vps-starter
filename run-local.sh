#!/bin/bash
# Local development runner (macOS / Linux with Docker Desktop).
# Starts the stack in DRY_RUN mode on alternate ports — no paid API calls.
#   Dashboard:    http://localhost:8090   (password: local-dev-password)
#   Landing page: http://localhost:8091
set -euo pipefail
cd "$(dirname "$0")"

command -v docker >/dev/null || { echo "Docker is required — install Docker Desktop."; exit 1; }

if [ ! -f .env ]; then
  HASH="$(python3 - <<'PY'
import hashlib, os
salt = os.urandom(16).hex()
h = hashlib.pbkdf2_hmac("sha256", b"local-dev-password", bytes.fromhex(salt), 200000).hex()
print(f"pbkdf2_sha256:200000:{salt}:{h}")
PY
)"
  cat > .env <<EOF
DASHBOARD_PASSWORD_HASH=${HASH}
SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
PUBLIC_IP=127.0.0.1
DRY_RUN=1
CERT_STAGING=1
EOF
  echo "Wrote dev .env (dashboard password: local-dev-password)"
fi

docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build
echo
echo "Dashboard:    http://localhost:8090  (password: local-dev-password)"
echo "Landing page: http://localhost:8091"
