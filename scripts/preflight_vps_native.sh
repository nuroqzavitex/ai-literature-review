#!/usr/bin/env bash
# Check whether the native VPS runtime is ready. If anything is missing, bootstrap
# the VPS by running the main setup script.

set -Eeuo pipefail

APP_DIR="${APP_DIR:-/root/P-178}"
DOMAIN="${DOMAIN:-c3-app-178.io.vn}"

missing=0
if [[ ! -f "${APP_DIR}/.env" ]]; then
    echo '[deploy] missing root env'
    missing=1
fi
if ! command -v psql >/dev/null 2>&1; then
    echo '[deploy] missing psql client'
    missing=1
fi
if ! systemctl is-active --quiet postgresql 2>/dev/null; then
    echo '[deploy] missing or inactive postgresql service'
    missing=1
fi
if ! ss -ltn 2>/dev/null | grep -q ':5432 '; then
    echo '[deploy] postgresql port 5432 not listening'
    missing=1
fi
if ! systemctl is-active --quiet redis-server.service 2>/dev/null; then
    echo '[deploy] missing or inactive redis-server service'
    missing=1
fi
if ! redis-cli -h 127.0.0.1 ping 2>/dev/null | grep -qx 'PONG'; then
    echo '[deploy] redis is not responding on 127.0.0.1:6379'
    missing=1
fi
if [[ ! -f /etc/systemd/system/qdrant.service || ! -f /etc/systemd/system/litreview-backend.service || ! -f /etc/systemd/system/litreview-worker.service || ! -f /etc/systemd/system/litreview-frontend.service ]]; then
    echo '[deploy] missing systemd units'
    missing=1
fi
if [[ ! -f /etc/nginx/sites-available/litreview-agent ]]; then
    echo '[deploy] missing nginx site'
    missing=1
fi
if [[ ! -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]]; then
    echo '[deploy] missing ssl certificate'
    missing=1
fi

if [[ "${missing}" -eq 1 ]]; then
    echo '[deploy] bootstrapping VPS environment'
    cd "${APP_DIR}"
    bash scripts/setup_vps_native_ubuntu_20_04.sh
else
    echo '[deploy] VPS environment already prepared'
fi
