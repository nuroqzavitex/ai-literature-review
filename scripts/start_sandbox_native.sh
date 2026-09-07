#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/root/P-178}"
ENV_FILE="${APP_DIR}/.env"

read_env() {
    local key="$1"
    [[ -f "${ENV_FILE}" ]] || return 0
    awk -v key="${key}" '
        $0 ~ "^" key "=" {
            sub("^" key "=", "")
            sub(/\r$/, "")
            gsub(/^\047|\047$/, "")
            gsub(/^\042|\042$/, "")
            value = $0
        }
        END { print value }
    ' "${ENV_FILE}"
}

CONTROL_URL="${SANDBOX_CONTROL_URL:-$(read_env SANDBOX_CONTROL_URL)}"
CONTROL_URL="${CONTROL_URL:-http://127.0.0.1:8081}"
WORKER_PROBE_PORT="${SANDBOX_WORKER_PROBE_PORT:-$(read_env SANDBOX_WORKER_PROBE_PORT)}"
WORKER_PROBE_PORT="${WORKER_PROBE_PORT:-8090}"

if [[ "$(id -u)" -ne 0 ]]; then
    echo '[sandbox-native] ERROR: run as root' >&2
    exit 1
fi

systemctl start sandbox-migrate.service
systemctl restart sandbox-control.service sandbox-worker.service

wait_for_ready() {
    local name="$1" url="$2" attempt
    for attempt in $(seq 1 30); do
        if curl --fail --silent --show-error --max-time 3 "${url}" >/dev/null; then
            echo "[sandbox-native] ${name} is ready: ${url}"
            return 0
        fi
        sleep 1
    done
    return 1
}

if ! wait_for_ready control "${CONTROL_URL%/}/readyz"; then
    echo
    echo '[sandbox-native] control readiness check failed' >&2
    journalctl -u sandbox-control.service -n 120 --no-pager >&2 || true
    exit 1
fi
if ! wait_for_ready worker "http://127.0.0.1:${WORKER_PROBE_PORT}/readyz"; then
    echo
    echo '[sandbox-native] worker readiness check failed' >&2
    journalctl -u sandbox-worker.service -n 120 --no-pager >&2 || true
    exit 1
fi
systemctl --no-pager --full status sandbox-migrate.service sandbox-control.service sandbox-worker.service || true
echo
echo "[sandbox-native] control is running at ${CONTROL_URL}"
echo "[sandbox-native] logs: journalctl -u sandbox-control.service -u sandbox-worker.service -f"
