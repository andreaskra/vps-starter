#!/bin/bash
# VPS starter kit — one-command installer for a fresh Ubuntu server.
# Usage:  bash setup.sh                 (first install / restart)
#         bash setup.sh --reset-password
set -euo pipefail

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || fail "Please run as root (you are root in the browser terminal by default)."
command -v apt-get >/dev/null || fail "This installer expects Ubuntu/Debian (apt-get not found)."
cd "$(dirname "$0")"

# ---- base tools ----
if ! command -v curl >/dev/null || ! command -v python3 >/dev/null; then
  say "Installing base tools (curl, python3)…"
  apt-get update -qq && apt-get install -y -qq curl python3 >/dev/null
fi

# ---- docker ----
if ! command -v docker >/dev/null; then
  say "Installing Docker (this takes a minute)…"
  curl -fsSL https://get.docker.com | sh >/dev/null
fi
docker compose version >/dev/null 2>&1 || fail "Docker Compose plugin missing — rerun this script."

hash_password() {
  python3 - "$1" <<'PY'
import hashlib, os, sys
pw = sys.argv[1]
salt = os.urandom(16).hex()
h = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200000).hex()
# colon-delimited: docker compose interpolates `$` in env_file values
print(f"pbkdf2_sha256:200000:{salt}:{h}")
PY
}

prompt_password() {
  # Non-interactive mode (used by AI-assisted deploys): pass DASHBOARD_PASSWORD
  # in the environment and no prompt appears.
  if [ -n "${DASHBOARD_PASSWORD:-}" ]; then
    [ "${#DASHBOARD_PASSWORD}" -ge 8 ] || fail "DASHBOARD_PASSWORD must be at least 8 characters."
    PASSWORD_HASH="$(hash_password "$DASHBOARD_PASSWORD")"
    return
  fi
  local pw pw2
  while true; do
    read -rs -p "Choose a dashboard password (min 8 characters): " pw; echo
    [ "${#pw}" -ge 8 ] || { echo "Too short — try again."; continue; }
    read -rs -p "Type it once more: " pw2; echo
    [ "$pw" = "$pw2" ] || { echo "Didn't match — try again."; continue; }
    break
  done
  PASSWORD_HASH="$(hash_password "$pw")"
}

# ---- .env ----
if [ "${1:-}" = "--reset-password" ]; then
  [ -f .env ] || fail "No .env yet — run 'bash setup.sh' first."
  prompt_password
  python3 - "$PASSWORD_HASH" <<'PY'
import sys
lines = [l for l in open(".env") if not l.startswith("DASHBOARD_PASSWORD_HASH=")]
lines.append(f"DASHBOARD_PASSWORD_HASH={sys.argv[1]}\n")
open(".env", "w").writelines(lines)
PY
  say "Password updated — restarting the dashboard…"
  docker compose up -d --force-recreate leadfinder
  exit 0
fi

if [ ! -f .env ]; then
  say "First-time setup."
  prompt_password
  SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  PUBLIC_IP="$(curl -fsS --max-time 10 https://api.ipify.org || true)"
  cat > .env <<EOF
DASHBOARD_PASSWORD_HASH=${PASSWORD_HASH}
SECRET_KEY=${SECRET_KEY}
PUBLIC_IP=${PUBLIC_IP}
DRY_RUN=0
CERT_STAGING=0
EOF
  chmod 600 .env
else
  say "Existing .env found — keeping your password and settings."
  PUBLIC_IP="$(grep '^PUBLIC_IP=' .env | cut -d= -f2- || true)"
fi

# ---- firewall (only if ufw is active) ----
if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q "Status: active"; then
  say "Opening firewall ports 22, 80, 443, 8080…"
  ufw allow 22/tcp >/dev/null; ufw allow 80/tcp >/dev/null
  ufw allow 443/tcp >/dev/null; ufw allow 8080/tcp >/dev/null
fi

# ---- build & start ----
say "Building and starting the containers (2–3 minutes on first run)…"
docker compose up -d --build

IP="${PUBLIC_IP:-<your-server-ip>}"
cat <<EOF

  ┌──────────────────────────────────────────────────────────┐
  │  All running! Open these in your browser:                │
  │                                                          │
  │  Dashboard:     http://${IP}
  │  Landing page:  http://${IP}:8080
  │                                                          │
  │  Log in with the password you just chose, then add       │
  │  your API keys under Settings.                           │
  └──────────────────────────────────────────────────────────┘

EOF
