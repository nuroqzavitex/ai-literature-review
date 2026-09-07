#!/usr/bin/env bash
# Bootstrap an Ubuntu EC2 instance for the Docker-based LitReview Agent stack.
#
# Usage:
#   sudo bash scripts/setup_ec2_ubuntu.sh c3-app-178.io.vn admin@example.com
#
# The script installs Docker Engine, configures the Docker Compose stack as a
# systemd service, installs Nginx as the public reverse proxy, and optionally
# obtains a Let's Encrypt certificate.

set -Eeuo pipefail
umask 027

APP_DIR="${APP_DIR:-/home/ubuntu/P-178}"
DEPLOY_USER="${DEPLOY_USER:-ubuntu}"
DOMAIN="${1:-${DOMAIN:-c3-app-178.io.vn}}"
CERTBOT_EMAIL="${2:-${CERTBOT_EMAIL:-xphuong0365921103@gmail.com}}"
ENABLE_SSL="${ENABLE_SSL:-true}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose-production.yml}"
NGINX_SITE="/etc/nginx/sites-available/litreview-agent"
NGINX_ENABLED="/etc/nginx/sites-enabled/litreview-agent"
SYSTEMD_UNIT="/etc/systemd/system/litreview-docker.service"

log() {
    printf '[setup-ec2] %s\n' "$*"
}

fail() {
    printf '[setup-ec2] ERROR: %s\n' "$*" >&2
    exit 1
}

require_root() {
    [[ "${EUID}" -eq 0 ]] || fail "Run this script with sudo or as root."
}

check_operating_system() {
    # shellcheck disable=SC1091
    source /etc/os-release
    [[ "${ID:-}" == "ubuntu" ]] || fail "This script supports Ubuntu only."
    [[ "$(dpkg --print-architecture)" == "amd64" ]] || fail "This EC2 script expects amd64/x86_64."
}

check_project() {
    [[ -d "${APP_DIR}" ]] || fail "Project directory not found: ${APP_DIR}"
    [[ -f "${APP_DIR}/${COMPOSE_FILE}" ]] || fail "Missing ${APP_DIR}/${COMPOSE_FILE}"

    if [[ ! -f "${APP_DIR}/.env" ]]; then
        [[ -f "${APP_DIR}/.env.example" ]] || fail "Missing ${APP_DIR}/.env.example"
        cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
        chown "${DEPLOY_USER}:${DEPLOY_USER}" "${APP_DIR}/.env" 2>/dev/null || true
        chmod 600 "${APP_DIR}/.env"
        fail "Created ${APP_DIR}/.env from .env.example. Fill production secrets, then rerun this script."
    fi

    chmod 600 "${APP_DIR}/.env"
}

install_docker() {
    export DEBIAN_FRONTEND=noninteractive

    local docker_installed=false
    local compose_installed=false

    if command -v docker >/dev/null 2>&1; then
        docker_installed=true
    fi
    if docker compose version >/dev/null 2>&1; then
        compose_installed=true
    fi

    if [[ "${docker_installed}" == true && "${compose_installed}" == true ]]; then
        log "Docker Engine and Docker Compose are already installed; skipping package installation."
        systemctl enable --now docker
        usermod -aG docker "${DEPLOY_USER}" 2>/dev/null || true
        return
    fi

    log "Installing Docker Engine from the official Docker repository"
    apt-get update
    apt-get install -y ca-certificates curl

    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc

    cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

    apt-get update
    local -a docker_packages=(
        docker-ce
        docker-ce-cli
        containerd.io
        docker-buildx-plugin
        docker-compose-plugin
    )
    apt-get install -y "${docker_packages[@]}"

    systemctl enable --now docker

    if id "${DEPLOY_USER}" >/dev/null 2>&1; then
        usermod -aG docker "${DEPLOY_USER}"
    fi
}

write_systemd_unit() {
    log "Creating systemd service for Docker Compose"
    cat > "${SYSTEMD_UNIT}" <<EOF
[Unit]
Description=LitReview Agent Docker Compose Stack
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=${APP_DIR}
ExecStart=/usr/bin/docker compose -f ${COMPOSE_FILE} up -d --build
ExecStop=/usr/bin/docker compose -f ${COMPOSE_FILE} down
RemainAfterExit=yes
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable litreview-docker.service
}

write_nginx_config() {
    log "Creating Nginx reverse proxy for ${DOMAIN}"
    install -d -m 0755 /var/www/html

    cat > "${NGINX_SITE}" <<NGINX
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

    client_max_body_size 32m;

    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location = /api {
        return 308 /api/v1/;
    }

    location /api/v1/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300;
        proxy_send_timeout 300;
    }

    location /health {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /_next/static/ {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    location / {
        proxy_pass http://127.0.0.1:3000;
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
NGINX

    ln -sfn "${NGINX_SITE}" "${NGINX_ENABLED}"
    rm -f /etc/nginx/sites-enabled/default

    nginx -t
    systemctl enable --now nginx
    systemctl reload nginx
}

request_ssl_certificate() {
    [[ "${ENABLE_SSL}" == "true" ]] || {
        log "Skipping SSL because ENABLE_SSL=${ENABLE_SSL}"
        return
    }

    [[ -n "${CERTBOT_EMAIL}" ]] || {
        log "Skipping SSL because no email was supplied."
        log "Run again with: sudo bash scripts/setup_ec2_ubuntu.sh ${DOMAIN} your@email.com"
        return
    }

    log "Installing Certbot and requesting HTTPS certificate"
    apt-get install -y certbot python3-certbot-nginx
    if certbot --nginx --non-interactive --agree-tos --redirect \
        --email "${CERTBOT_EMAIL}" -d "${DOMAIN}"; then
        systemctl reload nginx
    else
        log "Certbot failed. Confirm DNS points to this EC2 and ports 80/443 are open, then rerun."
    fi
}

start_stack() {
    log "Validating Docker Compose configuration"
    cd "${APP_DIR}"
    docker compose -f "${COMPOSE_FILE}" config --quiet

    log "Starting production application containers"
    systemctl restart litreview-docker.service
    wait_for_stack
    cleanup_docker
    docker compose -f "${COMPOSE_FILE}" ps
}

wait_for_stack() {
    log "Waiting for the application health checks"
    local deadline=$((SECONDS + 300))
    while (( SECONDS < deadline )); do
        local backend_id frontend_id sandbox_id backend_status frontend_status sandbox_status
        backend_id="$(docker compose -f "${COMPOSE_FILE}" ps -q backend 2>/dev/null || true)"
        frontend_id="$(docker compose -f "${COMPOSE_FILE}" ps -q frontend 2>/dev/null || true)"
        sandbox_id="$(docker compose -f "${COMPOSE_FILE}" ps -q sandbox-control 2>/dev/null || true)"
        backend_status="$(docker inspect --format '{{.State.Health.Status}}' "${backend_id}" 2>/dev/null || true)"
        frontend_status="$(docker inspect --format '{{.State.Status}}' "${frontend_id}" 2>/dev/null || true)"
        sandbox_status="$(docker inspect --format '{{.State.Health.Status}}' "${sandbox_id}" 2>/dev/null || true)"
        if [[ "${backend_status}" == "healthy" && "${frontend_status}" == "running" && ( -z "${sandbox_id}" || "${sandbox_status}" == "healthy" ) ]]; then
            log "Backend, frontend and enabled dependencies are ready"
            return
        fi
        sleep 5
    done

    docker compose -f "${COMPOSE_FILE}" ps
    fail "Application did not become healthy within 300 seconds. Check: docker compose -f ${COMPOSE_FILE} logs --tail=200"
}

cleanup_docker() {
    [[ "${PRUNE_DOCKER:-true}" == "true" ]] || {
        log "Skipping Docker cleanup because PRUNE_DOCKER=${PRUNE_DOCKER}"
        return
    }

    log "Removing stopped containers, unused images and build cache"
    # These commands never remove Docker volumes, so PostgreSQL, Qdrant,
    # Redis, MinIO and Sandbox data remain intact.
    docker container prune --force
    # sandbox-runtime-image is intentionally a one-shot Compose service. The
    # worker launches the immutable ID written to the metadata volume, not
    # the tag. Protect both references while image prune runs.
    local runtime_image="${SANDBOX_RUNTIME_IMAGE_NAME:-sandbox_runtime:latest}"
    local control_id metadata_volume runtime_digest
    local -a protect_containers=()
    control_id="$(docker compose -f "${COMPOSE_FILE}" ps -q sandbox-control 2>/dev/null || true)"
    metadata_volume="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/run/sandbox-runtime"}}{{.Name}}{{end}}{{end}}' "${control_id}" 2>/dev/null || true)"
    runtime_digest="$(docker run --rm -v "${metadata_volume}:/metadata:ro" alpine:3.22 cat /metadata/image-ref 2>/dev/null || true)"

    local candidate protect_container
    for candidate in "${runtime_image}" "${runtime_digest}"; do
        [[ -n "${candidate}" ]] || continue
        if docker image inspect "${candidate}" >/dev/null 2>&1; then
            protect_container="p178-prune-protect-$RANDOM"
            docker create --name "${protect_container}" "${candidate}" >/dev/null
            protect_containers+=("${protect_container}")
        fi
    done
    docker image prune --all --force
    docker builder prune --all --force
    for protect_container in "${protect_containers[@]}"; do
        docker rm -f "${protect_container}" >/dev/null 2>&1 || true
    done
}

main() {
    require_root
    check_operating_system
    check_project
    install_docker
    write_systemd_unit
    start_stack
    write_nginx_config
    request_ssl_certificate

    log "EC2 setup completed."
    log "App directory: ${APP_DIR}"
    log "View containers: docker compose -f ${APP_DIR}/${COMPOSE_FILE} ps"
    log "Future deploy: cd ${APP_DIR} && git pull && sudo systemctl restart litreview-docker.service"
    log "Disable cleanup when needed: PRUNE_DOCKER=false sudo systemctl restart litreview-docker.service"
}

main "$@"
