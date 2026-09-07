#!/usr/bin/env bash
# Install the Sandbox control plane and worker as native systemd services.
# The analysis runtime uses bubblewrap; Docker is not required.

set -Eeuo pipefail
umask 027

APP_DIR="${APP_DIR:-/root/P-178}"
APP_USER="${APP_USER:-$(stat -c '%U' "${APP_DIR}")}" 
APP_GROUP="${APP_GROUP:-$(id -gn "${APP_USER}")}"
BOOTSTRAP_PYTHON="${BOOTSTRAP_PYTHON:-python3.12}"
SANDBOX_VENV_DIR="${SANDBOX_VENV_DIR:-${APP_DIR}/.sandbox-venv}"
PYTHON_BIN="${PYTHON_BIN:-${SANDBOX_VENV_DIR}/bin/python}"
RUNTIME_ROOT="${SANDBOX_NATIVE_RUNTIME_ROOT:-/var/lib/research-sandbox/native-runtime}"
STORAGE_ROOT="${SANDBOX_LOCAL_STORAGE_PATH:-/var/lib/research-sandbox/storage}"
CONTROL_HOST="${SANDBOX_CONTROL_HOST:-127.0.0.1}"
CONTROL_PORT="${SANDBOX_CONTROL_PORT:-8081}"
WORKER_PROBE_PORT="${SANDBOX_WORKER_PROBE_PORT:-8090}"
ENV_FILE="${APP_DIR}/.env"

fail() { printf '[sandbox-native] ERROR: %s\n' "$*" >&2; exit 1; }
log() { printf '[sandbox-native] %s\n' "$*"; }

[[ "$(id -u)" -eq 0 ]] || fail "Run as root."
[[ -d "${APP_DIR}/research-sandbox" ]] || fail "Missing ${APP_DIR}/research-sandbox."
[[ -f "${ENV_FILE}" ]] || fail "Missing ${ENV_FILE}."

log "Installing native isolation prerequisites."
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends bubblewrap util-linux curl ca-certificates python3-venv
command -v bwrap >/dev/null 2>&1 || fail "bubblewrap installation failed."
command -v prlimit >/dev/null 2>&1 || fail "util-linux installation failed."
command -v curl >/dev/null 2>&1 || fail "curl installation failed."

if [[ ! -x "${PYTHON_BIN}" ]]; then
    command -v "${BOOTSTRAP_PYTHON}" >/dev/null 2>&1 || fail "Missing bootstrap Python: ${BOOTSTRAP_PYTHON}."
    log "Creating Sandbox control-plane virtualenv at ${SANDBOX_VENV_DIR}."
    "${BOOTSTRAP_PYTHON}" -m venv "${SANDBOX_VENV_DIR}"
fi
[[ -x "${PYTHON_BIN}" ]] || fail "Missing Python environment: ${PYTHON_BIN}."

if ! id sandbox >/dev/null 2>&1; then
    useradd --system --uid 10001 --home-dir /var/lib/research-sandbox --shell /usr/sbin/nologin sandbox
fi
# The parent is only a traversal boundary. Sensitive children retain their own
# restrictive ownership and modes; APP_USER must still be able to reach them.
install -d -m 0755 -o root -g root /var/lib/research-sandbox

log "Installing pinned Sandbox control-plane dependencies."
"${PYTHON_BIN}" -m pip install --require-hashes -r "${APP_DIR}/research-sandbox/requirements.control.lock"
"${PYTHON_BIN}" -m pip install --no-deps -e "${APP_DIR}/research-sandbox"
# The bootstrap is normally executed as root while both native services run as
# APP_USER.  A restrictive umask would otherwise leave the virtualenv
# untraversable and make systemd fail with "Permission denied".
chown -R "${APP_USER}:${APP_GROUP}" "${SANDBOX_VENV_DIR}"
chmod 0750 "${SANDBOX_VENV_DIR}" "${SANDBOX_VENV_DIR}/bin"

log "Preparing the native runtime virtualenv and read-only SDK."
install -d -m 0755 -o sandbox -g sandbox "${RUNTIME_ROOT}"
if [[ ! -x "${RUNTIME_ROOT}/venv/bin/python" ]]; then
    "${PYTHON_BIN}" -m venv "${RUNTIME_ROOT}/venv"
fi
"${RUNTIME_ROOT}/venv/bin/python" -m pip install --require-hashes -r "${APP_DIR}/research-sandbox/sandbox_runtime/requirements.lock"
rm -rf "${RUNTIME_ROOT}/sandbox_sdk"
cp -a "${APP_DIR}/research-sandbox/sandbox_runtime/sandbox_sdk" "${RUNTIME_ROOT}/sandbox_sdk"
chown -R root:root "${RUNTIME_ROOT}/sandbox_sdk" "${RUNTIME_ROOT}/venv"
chmod -R a-w "${RUNTIME_ROOT}/sandbox_sdk"
chmod -R a+rX "${RUNTIME_ROOT}/venv"
chmod -R a-w "${RUNTIME_ROOT}/venv"
chmod 0755 "${RUNTIME_ROOT}" "${RUNTIME_ROOT}/venv" "${RUNTIME_ROOT}/venv/bin/python"

runtime_hash="$(
    cd "${APP_DIR}/research-sandbox/sandbox_runtime"
    {
        sha256sum requirements.lock
        find sandbox_sdk -type f -print0 | sort -z | xargs -0 sha256sum
    } | sha256sum | awk '{print $1}'
)"
read_env() {
    local key="$1"
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
upsert_env() {
    local key="$1" value="$2" tmp
    tmp="$(mktemp)"
    awk -v key="${key}" -v value="${value}" '
        BEGIN { done = 0 }
        $0 ~ "^" key "=" { if (!done) { print key "=" value; done = 1 }; next }
        { print }
        END { if (!done) print key "=" value }
    ' "${ENV_FILE}" > "${tmp}"
    install -m 0600 -o "${APP_USER}" -g "${APP_GROUP}" "${tmp}" "${ENV_FILE}"
    rm -f "${tmp}"
}

database_url="$(read_env SANDBOX_DATABASE_URL)"
[[ -n "${database_url}" ]] || database_url="$(read_env PRODUCT_DATABASE_URL)"
[[ -n "${database_url}" ]] || database_url="$(read_env DATABASE_URL)"
[[ -n "${database_url}" ]] || fail "Configure SANDBOX_DATABASE_URL, PRODUCT_DATABASE_URL or DATABASE_URL in ${ENV_FILE}."
case "${database_url}" in
    postgresql://*) database_url="postgresql+psycopg://${database_url#postgresql://}" ;;
    postgres://*) database_url="postgresql+psycopg://${database_url#postgres://}" ;;
esac

storage_backend="$(read_env SANDBOX_OBJECT_STORAGE_BACKEND)"
storage_backend="${storage_backend:-local}"
sandbox_environment="$(read_env SANDBOX_ENVIRONMENT)"
sandbox_environment="${sandbox_environment:-development}"
if [[ "${sandbox_environment}" == "production" && "${storage_backend}" != "s3" ]]; then
    fail "Production native Sandbox requires SANDBOX_OBJECT_STORAGE_BACKEND=s3 and an S3 bucket."
fi
if [[ "${storage_backend}" == "s3" ]]; then
    [[ -n "$(read_env SANDBOX_OBJECT_STORAGE_BUCKET)" ]] || fail "S3 storage requires SANDBOX_OBJECT_STORAGE_BUCKET."
elif [[ "${storage_backend}" != "local" ]]; then
    fail "SANDBOX_OBJECT_STORAGE_BACKEND must be local or s3."
fi

upsert_env SANDBOX_PERSISTENCE_BACKEND postgres
upsert_env SANDBOX_DATABASE_URL "${database_url}"
upsert_env SANDBOX_OBJECT_STORAGE_BACKEND "${storage_backend}"
if [[ "${storage_backend}" == "local" ]]; then
    upsert_env SANDBOX_LOCAL_STORAGE_PATH "${STORAGE_ROOT}"
fi
upsert_env SANDBOX_RUNTIME_LAUNCHER native
upsert_env SANDBOX_RUNTIME_PYTHON "${RUNTIME_ROOT}/venv/bin/python"
upsert_env SANDBOX_RUNTIME_SDK_PATH "${RUNTIME_ROOT}/sandbox_sdk"
upsert_env SANDBOX_BWRAP_BINARY "$(command -v bwrap)"
upsert_env SANDBOX_RUNTIME_IMAGE_DIGEST "native-runtime@sha256:${runtime_hash}"
upsert_env SANDBOX_PACKAGE_MANIFEST_HASH "${runtime_hash}"
upsert_env SANDBOX_RUNTIME_IMAGE_NAME native-runtime
upsert_env SANDBOX_RUNTIME_WORKSPACE_PATH "${APP_DIR}/research-sandbox/.sandbox-workspaces"
upsert_env SANDBOX_CONTROL_URL "http://${CONTROL_HOST}:${CONTROL_PORT}"
upsert_env SANDBOX_WORKER_PROBE_PORT "${WORKER_PROBE_PORT}"

install -d -m 0700 -o "${APP_USER}" -g "${APP_GROUP}" "${APP_DIR}/research-sandbox/.sandbox-workspaces"
install -d -m 0700 -o "${APP_USER}" -g "${APP_GROUP}" "${STORAGE_ROOT}"
install -d -m 0750 -o "${APP_USER}" -g "${APP_GROUP}" "${APP_DIR}/logs"

cat > /etc/systemd/system/sandbox-migrate.service <<EOF
[Unit]
Description=Research Sandbox database migration
After=postgresql.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=${APP_USER}
Group=${APP_GROUP}
WorkingDirectory=${APP_DIR}/research-sandbox
EnvironmentFile=${ENV_FILE}
Environment=PYTHONPATH=${APP_DIR}:${APP_DIR}/research-sandbox
ExecStart=${PYTHON_BIN} -m alembic -c alembic.ini upgrade head
EOF

cat > /etc/systemd/system/sandbox-control.service <<EOF
[Unit]
Description=Research Sandbox control plane
After=network-online.target postgresql.service sandbox-migrate.service
Wants=network-online.target
Requires=sandbox-migrate.service

[Service]
Type=simple
User=${APP_USER}
Group=${APP_GROUP}
WorkingDirectory=${APP_DIR}/research-sandbox
EnvironmentFile=${ENV_FILE}
Environment=PYTHONPATH=${APP_DIR}:${APP_DIR}/research-sandbox
ExecStart=${PYTHON_BIN} -m uvicorn sandbox_service.main:app --host ${CONTROL_HOST} --port ${CONTROL_PORT}
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
UMask=0077
ReadWritePaths=${APP_DIR}/research-sandbox/.sandbox-workspaces ${STORAGE_ROOT} ${APP_DIR}/logs
StandardOutput=append:${APP_DIR}/logs/sandbox-control.log
StandardError=append:${APP_DIR}/logs/sandbox-control.log

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/sandbox-worker.service <<EOF
[Unit]
Description=Research Sandbox native execution worker
After=network-online.target postgresql.service sandbox-migrate.service
Wants=network-online.target
Requires=sandbox-migrate.service

[Service]
Type=simple
User=${APP_USER}
Group=${APP_GROUP}
WorkingDirectory=${APP_DIR}/research-sandbox
EnvironmentFile=${ENV_FILE}
Environment=PYTHONPATH=${APP_DIR}:${APP_DIR}/research-sandbox
Environment=SANDBOX_WORKER_FACTORY=sandbox_service.worker.factory:create_production_worker
Environment=SANDBOX_WORKER_PROBE_HOST=127.0.0.1
Environment=SANDBOX_WORKER_PROBE_PORT=${WORKER_PROBE_PORT}
ExecStart=${PYTHON_BIN} -m sandbox_service.worker.main
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=false
UMask=0077
ReadWritePaths=${APP_DIR}/research-sandbox/.sandbox-workspaces ${STORAGE_ROOT} ${APP_DIR}/logs
StandardOutput=append:${APP_DIR}/logs/sandbox-worker.log
StandardError=append:${APP_DIR}/logs/sandbox-worker.log

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable sandbox-control.service sandbox-worker.service
log "Native Sandbox units installed. Start with: bash scripts/start_sandbox_native.sh"
