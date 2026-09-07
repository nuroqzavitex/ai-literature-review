#!/usr/bin/env bash
# Build and deploy LitReview Agent directly on a VPS, without Docker.
# Can run as root or as a non-root deploy user created by setup_vps_native_ubuntu_20_04.sh.

set -Eeuo pipefail
umask 027

APP_DIR="${APP_DIR:-/root/P-178}"
PYTHON_BIN="${PYTHON_BIN:-python3.12}"
DEPLOY_REF="${DEPLOY_REF:-main}"
FRONTEND_DEPLOY_ROOT="${APP_DIR}/frontend/.deploy"
FRONTEND_RELEASES_DIR="${FRONTEND_DEPLOY_ROOT}/releases"
FRONTEND_CURRENT_LINK="${FRONTEND_DEPLOY_ROOT}/current"
FRONTEND_PREVIOUS_LINK="${FRONTEND_DEPLOY_ROOT}/previous"

APP_OWNER=""
APP_GROUP=""
FRONTEND_RELEASE_ID=""
FRONTEND_RELEASE_DIR=""
FRONTEND_STAGING_DIR=""

log() {
    printf '[deploy-native] %s\n' "$*"
}

fail() {
    printf '[deploy-native] ERROR: %s\n' "$*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

systemctl_cmd() {
    if [[ "${EUID}" -eq 0 ]]; then
        systemctl "$@"
    else
        sudo systemctl "$@"
    fi
}

write_root_file() {
    local path="$1"
    if [[ "${EUID}" -eq 0 ]]; then
        cat >"$path"
    else
        sudo tee "$path" >/dev/null
    fi
}

sync_source() {
    cd "${APP_DIR}"
    [[ -d ".git" ]] || fail "Missing .git in ${APP_DIR}. Clone the repository once before deploying."
    git config --global --add safe.directory "${APP_DIR}" >/dev/null 2>&1 || true
    log "Syncing source from origin/${DEPLOY_REF}"
    git fetch origin "${DEPLOY_REF}"
    git reset --hard "origin/${DEPLOY_REF}"
    git clean -fd
}

resolve_app_identity() {
    APP_OWNER="$(stat -c '%U' "${APP_DIR}")"
    APP_GROUP="$(stat -c '%G' "${APP_DIR}")"
}

load_env_file() {
    local env_file="$1"
    local line key value

    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line%$'\r'}"
        [[ -z "$line" || "$line" == \#* ]] && continue
        [[ "$line" == *=* ]] || continue

        key="${line%%=*}"
        value="${line#*=}"

        if [[ ${value:0:1} == '"' && ${value: -1} == '"' ]]; then
            value="${value:1:${#value}-2}"
        elif [[ ${value:0:1} == "'" && ${value: -1} == "'" ]]; then
            value="${value:1:${#value}-2}"
        fi

        export "$key=$value"
    done < "$env_file"
}
validate_source_tree() {
    [[ -f "${APP_DIR}/requirements.txt" ]] || fail "Missing ${APP_DIR}/requirements.txt."
    [[ -d "${APP_DIR}/frontend" ]] || fail "Missing ${APP_DIR}/frontend."
    [[ -f "${APP_DIR}/frontend/package.json" ]] || fail "Missing ${APP_DIR}/frontend/package.json."
}

prepare_environment() {
    if [[ ! -f "${APP_DIR}/.env" ]]; then
        cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
        chmod 600 "${APP_DIR}/.env"
        fail "Created ${APP_DIR}/.env. Fill the production values once, then rerun deploy."
    fi

    chmod 600 "${APP_DIR}/.env"
    local api_url app_env clerk_publishable_key clerk_secret_key qdrant_url redis_url redis_enabled
    api_url="$(sed -n 's/^NEXT_PUBLIC_API_BASE_URL=//p' "${APP_DIR}/.env" | tail -n 1)"
    app_env="$(sed -n 's/^APP_ENV=//p' "${APP_DIR}/.env" | tail -n 1)"
    clerk_publishable_key="$(sed -n 's/^NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=//p' "${APP_DIR}/.env" | tail -n 1)"
    clerk_secret_key="$(sed -n 's/^CLERK_SECRET_KEY=//p' "${APP_DIR}/.env" | tail -n 1)"
    qdrant_url="$(sed -n 's/^QDRANT_URL=//p' "${APP_DIR}/.env" | tail -n 1)"
    redis_url="$(sed -n 's/^REDIS_URL=//p' "${APP_DIR}/.env" | tail -n 1)"
    redis_enabled="$(sed -n 's/^REDIS_ENABLED=//p' "${APP_DIR}/.env" | tail -n 1)"
    [[ "${app_env}" == "production" ]] || fail "Set APP_ENV=production in ${APP_DIR}/.env."
    [[ -n "${api_url}" && "${api_url}" != *"localhost"* && "${api_url}" != *"127.0.0.1"* ]] || fail "Set NEXT_PUBLIC_API_BASE_URL to the public API URL, not localhost."
    [[ -n "${clerk_publishable_key}" ]] || fail "Set NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY in ${APP_DIR}/.env before building the frontend."
    [[ -n "${clerk_secret_key}" ]] || fail "Set CLERK_SECRET_KEY in ${APP_DIR}/.env for Clerk middleware."
    [[ "${qdrant_url}" == "http://127.0.0.1:6333" ]] || fail "Set QDRANT_URL=http://127.0.0.1:6333 for the native Qdrant service."
    [[ "${redis_enabled,,}" == "true" ]] || fail "Set REDIS_ENABLED=true for the native Redis service."
    [[ "${redis_url}" == "redis://127.0.0.1:6379/0" ]] || fail "Set REDIS_URL=redis://127.0.0.1:6379/0 for the native Redis service."
}

ensure_deploy_dirs() {
    mkdir -p "${FRONTEND_RELEASES_DIR}"
    if [[ "${EUID}" -eq 0 && "${APP_OWNER}" != "root" ]]; then
        chown -R "${APP_OWNER}:${APP_GROUP}" "${FRONTEND_DEPLOY_ROOT}"
    fi
}

write_frontend_service_unit() {
    if [[ "${EUID}" -eq 0 ]]; then
        cat > /etc/systemd/system/litreview-frontend.service <<EOF
[Unit]
Description=LitReview Agent Next.js Frontend
After=network-online.target litreview-backend.service
Wants=network-online.target litreview-backend.service

[Service]
Type=simple
User=${APP_OWNER}
Group=${APP_GROUP}
EnvironmentFile=-${APP_DIR}/.env
Environment=HOSTNAME=127.0.0.1
Environment=PORT=3000
WorkingDirectory=${FRONTEND_CURRENT_LINK}
ExecStart=/usr/bin/node ${FRONTEND_CURRENT_LINK}/server.js
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
StandardOutput=append:${APP_DIR}/logs/frontend.log
StandardError=append:${APP_DIR}/logs/frontend.log

[Install]
WantedBy=multi-user.target
EOF
    else
        sudo tee /etc/systemd/system/litreview-frontend.service >/dev/null <<EOF
[Unit]
Description=LitReview Agent Next.js Frontend
After=network-online.target litreview-backend.service
Wants=network-online.target litreview-backend.service

[Service]
Type=simple
User=${APP_OWNER}
Group=${APP_GROUP}
EnvironmentFile=-${APP_DIR}/.env
Environment=HOSTNAME=127.0.0.1
Environment=PORT=3000
WorkingDirectory=${FRONTEND_CURRENT_LINK}
ExecStart=/usr/bin/node ${FRONTEND_CURRENT_LINK}/server.js
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
StandardOutput=append:${APP_DIR}/logs/frontend.log
StandardError=append:${APP_DIR}/logs/frontend.log

[Install]
WantedBy=multi-user.target
EOF
    fi
}

prepare_frontend_release() {
    local previous_target
    FRONTEND_RELEASE_ID="$(date -u +%Y%m%d%H%M%S)-$(git -C "${APP_DIR}" rev-parse --short HEAD)"
    FRONTEND_RELEASE_DIR="${FRONTEND_RELEASES_DIR}/${FRONTEND_RELEASE_ID}"
    FRONTEND_STAGING_DIR="${FRONTEND_RELEASES_DIR}/.${FRONTEND_RELEASE_ID}.staging"
    rm -rf "${FRONTEND_STAGING_DIR}" "${FRONTEND_RELEASE_DIR}"
    mkdir -p "${FRONTEND_STAGING_DIR}/.next"

    log "Staging frontend release ${FRONTEND_RELEASE_ID}"
    rsync -a --delete "${APP_DIR}/frontend/.next/standalone/" "${FRONTEND_STAGING_DIR}/"
    rsync -a --delete "${APP_DIR}/frontend/.next/static/" "${FRONTEND_STAGING_DIR}/.next/static/"
    if [[ -d "${APP_DIR}/frontend/public" ]]; then
        rsync -a --delete "${APP_DIR}/frontend/public/" "${FRONTEND_STAGING_DIR}/public/"
    fi

    if [[ "${EUID}" -eq 0 && "${APP_OWNER}" != "root" ]]; then
        chown -R "${APP_OWNER}:${APP_GROUP}" "${FRONTEND_STAGING_DIR}"
    fi

    mv "${FRONTEND_STAGING_DIR}" "${FRONTEND_RELEASE_DIR}"

    previous_target=""
    if [[ -L "${FRONTEND_CURRENT_LINK}" ]]; then
        previous_target="$(readlink -f "${FRONTEND_CURRENT_LINK}" || true)"
    fi
    if [[ -n "${previous_target}" && "${previous_target}" != "${FRONTEND_RELEASE_DIR}" ]]; then
        ln -sfn "${previous_target}" "${FRONTEND_PREVIOUS_LINK}"
    fi
    ln -sfn "${FRONTEND_RELEASE_DIR}" "${FRONTEND_CURRENT_LINK}"
}

run_database_migrations() {
    log "Running database migrations"
    "${APP_DIR}/.venv/bin/python" -c "from src.config import get_settings; from src.services.repositories.database import run_migrations; settings = get_settings(); run_migrations(settings.product_database_url or settings.database_url)"
}

build_application() {
    sync_source
    resolve_app_identity
    ensure_deploy_dirs

    cd "${APP_DIR}"
    if [[ ! -x .venv/bin/python ]]; then
        log "Creating Python virtual environment at ${APP_DIR}/.venv"
        "${PYTHON_BIN}" -m venv .venv
    fi
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/pip install -r requirements.txt

    # Root .env is the single source of truth for backend runtime and frontend build.
    load_env_file .env

    run_database_migrations

    cd frontend
    if [[ ! -d node_modules ]]; then
        log "Installing frontend dependencies with npm ci"
    fi
    npm ci
    npm run build

    prepare_frontend_release
    write_frontend_service_unit
    systemctl_cmd daemon-reload
}

restart_services() {
    systemctl_cmd restart redis-server.service
    systemctl_cmd restart qdrant.service
    systemctl_cmd restart litreview-backend.service
    systemctl_cmd restart litreview-worker.service
    systemctl_cmd restart litreview-frontend.service
}

verify_backend_health() {
    local attempt
    for attempt in $(seq 1 20); do
        if curl --fail --silent --show-error http://127.0.0.1:8000/health >/dev/null; then
            log "Backend health check passed."
            return
        fi
        sleep 3
    done
    return 1
}

verify_frontend_health() {
    local attempt
    for attempt in $(seq 1 20); do
        if curl --fail --silent --show-error http://127.0.0.1:3000/ >/dev/null; then
            log "Frontend health check passed."
            return
        fi
        sleep 3
    done
    return 1
}

rollback_frontend_release() {
    local previous_target
    previous_target=""
    if [[ -L "${FRONTEND_PREVIOUS_LINK}" ]]; then
        previous_target="$(readlink -f "${FRONTEND_PREVIOUS_LINK}" || true)"
    elif [[ -L "${FRONTEND_CURRENT_LINK}" ]]; then
        previous_target="$(readlink -f "${FRONTEND_CURRENT_LINK}" || true)"
    fi

    [[ -n "${previous_target}" && -d "${previous_target}" ]] || return 1
    log "Rolling back frontend symlink to ${previous_target}"
    ln -sfn "${previous_target}" "${FRONTEND_CURRENT_LINK}"
    systemctl_cmd restart litreview-frontend.service
    return 0
}

cleanup_old_frontend_releases() {
    local current_target previous_target release_path
    current_target=""
    previous_target=""

    if [[ -L "${FRONTEND_CURRENT_LINK}" ]]; then
        current_target="$(readlink -f "${FRONTEND_CURRENT_LINK}" || true)"
    fi
    if [[ -L "${FRONTEND_PREVIOUS_LINK}" ]]; then
        previous_target="$(readlink -f "${FRONTEND_PREVIOUS_LINK}" || true)"
    fi

    shopt -s nullglob
    for release_path in "${FRONTEND_RELEASES_DIR}"/*; do
        [[ -d "${release_path}" ]] || continue
        if [[ "${release_path}" == "${current_target}" || "${release_path}" == "${previous_target}" ]]; then
            continue
        fi
        rm -rf "${release_path}"
    done
    shopt -u nullglob
}

restart_and_verify() {
    restart_services

    if ! verify_backend_health; then
        systemctl_cmd status qdrant.service --no-pager || true
        systemctl_cmd status redis-server.service --no-pager || true
        systemctl_cmd status litreview-backend.service --no-pager || true
        systemctl_cmd status litreview-worker.service --no-pager || true
        systemctl_cmd status litreview-frontend.service --no-pager || true
        fail "Backend did not become healthy."
    fi

    if ! verify_frontend_health; then
        systemctl_cmd status litreview-frontend.service --no-pager || true
        if rollback_frontend_release; then
            if ! verify_frontend_health; then
                fail "Frontend did not become healthy after rollback."
            fi
        else
            fail "Frontend did not become healthy and no rollback release was available."
        fi
    fi

    cleanup_old_frontend_releases
}

main() {
    if [[ "${EUID}" -ne 0 ]]; then
        require_command sudo
    fi
    require_command curl
    require_command npm
    require_command rsync
    require_command "${PYTHON_BIN}"

    validate_source_tree
    prepare_environment
    build_application
    restart_and_verify
}

main "$@"
