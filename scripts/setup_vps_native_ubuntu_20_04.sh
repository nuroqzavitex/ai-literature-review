#!/usr/bin/env bash
# Prepare Ubuntu for a native (non-Docker) LitReview Agent deployment.
# Run as root. The application services will run as root by default unless you
# override DEPLOY_USER.

set -Eeuo pipefail
umask 027

DEPLOY_USER="${DEPLOY_USER:-root}"
APP_DIR="${APP_DIR:-/root/P-178}"
QDRANT_VERSION="${QDRANT_VERSION:-1.16.2}"
PYTHON_VERSION="${PYTHON_VERSION:-3.12.13}"
PYTHON_BIN="${PYTHON_BIN:-python3.12}"
NGINX_SERVER_NAME="${NGINX_SERVER_NAME:-c3-app-178.io.vn}"
NGINX_UPSTREAM_FRONTEND="${NGINX_UPSTREAM_FRONTEND:-127.0.0.1:3000}"
NGINX_UPSTREAM_BACKEND="${NGINX_UPSTREAM_BACKEND:-127.0.0.1:8000}"
CERTBOT_EMAIL="${CERTBOT_EMAIL:-}"
CERTBOT_DOMAINS="${CERTBOT_DOMAINS:-${NGINX_SERVER_NAME}}"
ENABLE_SSL="${ENABLE_SSL:-true}"
POSTGRES_DB="${POSTGRES_DB:-litreview}"
POSTGRES_USER="${POSTGRES_USER:-litreview}"

log() {
    printf '[setup-native] %s\n' "$*"
}

fail() {
    printf '[setup-native] ERROR: %s\n' "$*" >&2
    exit 1
}

require_root() {
    [[ "${EUID}" -eq 0 ]] || fail "Run this script as root."
}

check_operating_system() {
    source /etc/os-release
    [[ "${ID:-}" == "ubuntu" ]] || fail "This script supports Ubuntu only."
    if [[ "${VERSION_ID:-}" == "20.04" ]]; then
        log "Ubuntu 20.04 is past standard support. This script does not run do-release-upgrade; plan a supported Ubuntu LTS upgrade."
    fi
}

available_root_gb() {
    df -Pk / | awk 'NR == 2 { printf "%.1f", $4 / 1024 / 1024 }'
}

cleanup_package_caches() {
    log "Free space on / before cleanup: $(available_root_gb) GB."
    apt-get clean || true
    rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*.deb /var/cache/apt/archives/partial/* || true
    rm -rf /root/.cache/pip "${APP_DIR}/frontend/.next/cache" "${APP_DIR}/frontend/node_modules/.cache" || true
    journalctl --vacuum-size=200M >/dev/null 2>&1 || true
    log "Free space on / after cleanup: $(available_root_gb) GB."
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
install_runtime_packages() {
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y --no-install-recommends \
        ca-certificates curl git gnupg rsync build-essential \
        libbz2-dev libffi-dev libgdbm-dev liblzma-dev libncursesw5-dev \
        libreadline-dev libsqlite3-dev libssl-dev libtk8.6 tk-dev \
        libuuid1 uuid-dev xz-utils zlib1g-dev

    install_python_from_source

    if ! command -v node >/dev/null 2>&1 || [[ "$(node --version | sed 's/^v//' | cut -d. -f1)" -lt 20 ]]; then
        curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
        apt-get install -y --no-install-recommends nodejs
    fi

    apt-get install -y --no-install-recommends nginx certbot python3-certbot-nginx redis-server
}

install_postgresql() {
    export DEBIAN_FRONTEND=noninteractive
    log "Installing PostgreSQL server..."
    apt-get install -y --no-install-recommends postgresql postgresql-contrib

    systemctl enable --now postgresql

    if command -v pg_isready >/dev/null 2>&1; then
        if ! pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
            log "Waiting for PostgreSQL to accept connections on 127.0.0.1:5432..."
            for _ in $(seq 1 30); do
                if pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
                    break
                fi
                sleep 1
            done
        fi
    fi
}

generate_postgres_password() {
    tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32
    printf '\n'
}

ensure_native_postgres_config() {
    local env_file="${APP_DIR}/.env"
    local postgres_password

    if [[ ! -f "${env_file}" ]]; then
        cp "${APP_DIR}/.env.example" "${env_file}"
    fi

    chmod 600 "${env_file}"

    if grep -q '^# BEGIN NATIVE POSTGRES$' "${env_file}"; then
        return
    fi

    postgres_password="$(generate_postgres_password)"
    cat >> "${env_file}" <<EOF

# BEGIN NATIVE POSTGRES
POSTGRES_DB=${POSTGRES_DB}
POSTGRES_USER=${POSTGRES_USER}
POSTGRES_PASSWORD=${postgres_password}
PRODUCT_DATABASE_URL=postgresql://${POSTGRES_USER}:${postgres_password}@127.0.0.1:5432/${POSTGRES_DB}
# END NATIVE POSTGRES
EOF

    chmod 600 "${env_file}"
}

ensure_native_redis_config() {
    local env_file="${APP_DIR}/.env"

    if [[ ! -f "${env_file}" ]]; then
        cp "${APP_DIR}/.env.example" "${env_file}"
    fi

    chmod 600 "${env_file}"
    if grep -q '^# BEGIN NATIVE REDIS$' "${env_file}"; then
        return
    fi

    cat >> "${env_file}" <<EOF

# BEGIN NATIVE REDIS
# Redis is local-only. PostgreSQL remains the durable source of truth.
REDIS_ENABLED=true
REDIS_URL=redis://127.0.0.1:6379/0
# END NATIVE REDIS
EOF
}

create_native_postgres_database() {
    local env_file="${APP_DIR}/.env"

    [[ -f "${env_file}" ]] || fail "Missing ${env_file}."

    load_env_file "${env_file}"

    [[ -n "${POSTGRES_DB:-}" && -n "${POSTGRES_USER:-}" && -n "${POSTGRES_PASSWORD:-}" ]] || fail "Missing native PostgreSQL settings in ${env_file}."

    log "Creating PostgreSQL role and database for ${POSTGRES_USER}/${POSTGRES_DB}..."

    if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname = '${POSTGRES_USER}'" | grep -q 1; then
        sudo -u postgres psql -v ON_ERROR_STOP=1 -c "CREATE ROLE ${POSTGRES_USER} LOGIN PASSWORD '${POSTGRES_PASSWORD}';"
    else
        sudo -u postgres psql -v ON_ERROR_STOP=1 -c "ALTER ROLE ${POSTGRES_USER} WITH LOGIN PASSWORD '${POSTGRES_PASSWORD}';"
    fi

    if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname = '${POSTGRES_DB}'" | grep -q 1; then
        sudo -u postgres createdb -O "${POSTGRES_USER}" "${POSTGRES_DB}"
    else
        sudo -u postgres psql -v ON_ERROR_STOP=1 -c "ALTER DATABASE ${POSTGRES_DB} OWNER TO ${POSTGRES_USER};"
    fi

    sudo -u postgres psql -v ON_ERROR_STOP=1 -c "GRANT ALL PRIVILEGES ON DATABASE ${POSTGRES_DB} TO ${POSTGRES_USER};"
}

install_python_from_source() {
    if command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
        log "${PYTHON_BIN} already available."
        return
    fi

    local build_dir source_url source_dir
    build_dir="$(mktemp -d)"
    trap 'rm -rf "${build_dir}"' RETURN

    source_url="https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tgz"
    log "Downloading Python ${PYTHON_VERSION} from python.org..."
    curl --fail --location --retry 3 --output "${build_dir}/Python.tgz" "${source_url}"
    tar -xzf "${build_dir}/Python.tgz" -C "${build_dir}"
    source_dir="${build_dir}/Python-${PYTHON_VERSION}"
    [[ -d "${source_dir}" ]] || fail "Python source directory not found after extraction."

    log "Building Python ${PYTHON_VERSION} from source..."
    (
        cd "${source_dir}"
        ./configure --prefix=/usr/local --with-ensurepip=install
        make -j"$(nproc)"
        make altinstall
    )
    /usr/local/bin/${PYTHON_BIN} -m pip install --upgrade pip setuptools wheel

    rm -rf "${build_dir}"
    trap - RETURN
}

install_nginx() {
    local site_avail site_enabled
    site_avail="/etc/nginx/sites-available/litreview-agent"
    site_enabled="/etc/nginx/sites-enabled/litreview-agent"

    cat > "${site_avail}" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${NGINX_SERVER_NAME};

    client_max_body_size 32m;

    location = /api {
        return 308 /api/v1/;
    }

    location /api/v1/ {
        proxy_pass http://${NGINX_UPSTREAM_BACKEND};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /_next/static/ {
        proxy_pass http://${NGINX_UPSTREAM_FRONTEND};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    location /health {
        proxy_pass http://${NGINX_UPSTREAM_BACKEND};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location / {
        proxy_pass http://${NGINX_UPSTREAM_FRONTEND};
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300;
        proxy_send_timeout 300;
    }
}
EOF

    ln -sf "${site_avail}" "${site_enabled}"
    rm -f /etc/nginx/sites-enabled/default
    nginx -t
    systemctl enable --now nginx
}

install_ssl_certificate() {
    if [[ "${ENABLE_SSL}" != "true" ]]; then
        log "Skipping SSL setup because ENABLE_SSL=${ENABLE_SSL}."
        return
    fi

    local -a certbot_args domain_args
    domain_args=()
    IFS=',' read -r -a domains <<< "${CERTBOT_DOMAINS}"
    for domain in "${domains[@]}"; do
        domain="${domain// /}"
        [[ -n "${domain}" ]] || continue
        domain_args+=(-d "${domain}")
    done
    [[ "${#domain_args[@]}" -gt 0 ]] || fail "CERTBOT_DOMAINS must contain at least one domain."

    certbot_args=(--nginx --non-interactive --agree-tos --redirect)
    if [[ -n "${CERTBOT_EMAIL}" ]]; then
        certbot_args+=(-m "${CERTBOT_EMAIL}")
    else
        certbot_args+=(--register-unsafely-without-email)
    fi

    log "Requesting Let's Encrypt certificate for: ${CERTBOT_DOMAINS}"
    certbot "${certbot_args[@]}" "${domain_args[@]}"
    systemctl reload nginx
}

create_application_user() {
    if ! id "${DEPLOY_USER}" >/dev/null 2>&1; then
        useradd --create-home --shell /bin/bash "${DEPLOY_USER}"
        log "Created deploy user '${DEPLOY_USER}'."
    fi
    install -d -m 0750 -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" "${APP_DIR}"
}

install_qdrant() {
    local archive_url temporary_dir qdrant_binary
    [[ "$(uname -m)" == "x86_64" ]] || fail "The native Qdrant package in this script supports x86_64 only."

    if ! id qdrant >/dev/null 2>&1; then
        useradd --system --home /var/lib/qdrant --shell /usr/sbin/nologin qdrant
    fi
    install -d -m 0750 -o qdrant -g qdrant /var/lib/qdrant
    install -d -m 0775 -o qdrant -g qdrant "${APP_DIR}/logs"

    if [[ ! -x /usr/local/bin/qdrant ]] || ! /usr/local/bin/qdrant --version 2>/dev/null | grep -q "${QDRANT_VERSION}"; then
        archive_url="https://github.com/qdrant/qdrant/releases/download/v${QDRANT_VERSION}/qdrant-x86_64-unknown-linux-musl.tar.gz"
        temporary_dir="$(mktemp -d)"
        trap 'rm -rf "${temporary_dir}"' RETURN
        curl --fail --location --retry 3 --output "${temporary_dir}/qdrant.tar.gz" "${archive_url}"
        tar -xzf "${temporary_dir}/qdrant.tar.gz" -C "${temporary_dir}"
        qdrant_binary="$(find "${temporary_dir}" -type f -name qdrant -perm -u+x -print -quit)"
        [[ -n "${qdrant_binary}" ]] || fail "Qdrant binary was not found in the downloaded archive."
        install -m 0755 "${qdrant_binary}" /usr/local/bin/qdrant
        rm -rf "${temporary_dir}"
        trap - RETURN
    fi

    cat > /etc/systemd/system/qdrant.service <<EOF
[Unit]
Description=Qdrant Vector Database
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=qdrant
Group=qdrant
WorkingDirectory=/var/lib/qdrant
Environment=QDRANT__SERVICE__HOST=127.0.0.1
Environment=QDRANT__SERVICE__HTTP_PORT=6333
Environment=QDRANT__SERVICE__GRPC_PORT=6334
Environment=QDRANT__STORAGE__STORAGE_PATH=/var/lib/qdrant/storage
Environment=QDRANT__STORAGE__SNAPSHOTS_PATH=/var/lib/qdrant/snapshots
ExecStart=/usr/local/bin/qdrant
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
StandardOutput=append:${APP_DIR}/logs/qdrant.log
StandardError=append:${APP_DIR}/logs/qdrant.log

[Install]
WantedBy=multi-user.target
EOF
}

install_redis() {
    local redis_config="/etc/redis/redis.conf"

    [[ -f "${redis_config}" ]] || fail "Redis configuration not found at ${redis_config}."
    if ! grep -q '^# BEGIN LITREVIEW REDIS$' "${redis_config}"; then
        cat >> "${redis_config}" <<'EOF'

# BEGIN LITREVIEW REDIS
# Keep Redis private to this VPS. Nginx never proxies this port.
bind 127.0.0.1 ::1
protected-mode yes
supervised systemd
appendonly yes
# END LITREVIEW REDIS
EOF
    fi

    systemctl daemon-reload
    systemctl enable --now redis-server.service
    if ! redis-cli -h 127.0.0.1 ping | grep -qx 'PONG'; then
        fail "Redis did not respond to a localhost health check."
    fi
}

install_application_services() {
    install -d -m 0750 -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" "${APP_DIR}/frontend/.deploy/releases"

    cat > /etc/systemd/system/litreview-backend.service <<EOF
[Unit]
Description=LitReview Agent FastAPI Backend
After=network-online.target qdrant.service redis-server.service
Wants=network-online.target qdrant.service redis-server.service

[Service]
Type=simple
User=${DEPLOY_USER}
Group=${DEPLOY_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=-${APP_DIR}/.env
Environment=WORKER_MODE=external
Environment=RUNTIME_ROLE=api
ExecStart=${APP_DIR}/.venv/bin/uvicorn src.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
StandardOutput=append:${APP_DIR}/logs/backend.log
StandardError=append:${APP_DIR}/logs/backend.log

[Install]
WantedBy=multi-user.target
EOF

    cat > /etc/systemd/system/litreview-worker.service <<EOF
[Unit]
Description=LitReview Agent Research Worker
After=network-online.target postgresql.service qdrant.service redis-server.service
Wants=network-online.target postgresql.service qdrant.service redis-server.service

[Service]
Type=simple
User=${DEPLOY_USER}
Group=${DEPLOY_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=-${APP_DIR}/.env
Environment=WORKER_MODE=external
Environment=RUNTIME_ROLE=worker
ExecStart=${APP_DIR}/.venv/bin/python -m src.worker_main
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
StandardOutput=append:${APP_DIR}/logs/worker.log
StandardError=append:${APP_DIR}/logs/worker.log

[Install]
WantedBy=multi-user.target
EOF

    cat > /etc/systemd/system/litreview-frontend.service <<EOF
[Unit]
Description=LitReview Agent Next.js Frontend
After=network-online.target litreview-backend.service
Wants=network-online.target litreview-backend.service

[Service]
Type=simple
User=${DEPLOY_USER}
Group=${DEPLOY_USER}
EnvironmentFile=-${APP_DIR}/.env
Environment=HOSTNAME=127.0.0.1
Environment=PORT=3000
WorkingDirectory=${APP_DIR}/frontend/.deploy/current
ExecStart=/usr/bin/node ${APP_DIR}/frontend/.deploy/current/server.js
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
StandardOutput=append:${APP_DIR}/logs/frontend.log
StandardError=append:${APP_DIR}/logs/frontend.log

[Install]
WantedBy=multi-user.target
EOF

    if [[ "${DEPLOY_USER}" != "root" ]]; then
        local systemctl_path
        systemctl_path="$(command -v systemctl)"
        cat > /etc/sudoers.d/litreview-services <<EOF
${DEPLOY_USER} ALL=(root) NOPASSWD: ${systemctl_path} restart redis-server.service, ${systemctl_path} restart qdrant.service, ${systemctl_path} restart litreview-backend.service, ${systemctl_path} restart litreview-worker.service, ${systemctl_path} restart litreview-frontend.service, ${systemctl_path} status redis-server.service, ${systemctl_path} status qdrant.service, ${systemctl_path} status litreview-backend.service, ${systemctl_path} status litreview-worker.service, ${systemctl_path} status litreview-frontend.service
EOF
        chmod 440 /etc/sudoers.d/litreview-services
        visudo -cf /etc/sudoers.d/litreview-services
    fi
    systemctl daemon-reload
    systemctl enable redis-server.service
    systemctl enable --now qdrant.service
    systemctl enable litreview-worker.service
}

main() {
    require_root
    check_operating_system
    cleanup_package_caches
    install_runtime_packages
    install_postgresql
    create_application_user
    ensure_native_postgres_config
    ensure_native_redis_config
    create_native_postgres_database
    install_redis
    install_qdrant
    install_application_services
    install_nginx
    install_ssl_certificate

    log "Native runtime setup is complete. Run scripts/deploy_vps_native.sh as '${DEPLOY_USER}'."
}

main "$@"
