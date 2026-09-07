#!/usr/bin/env bash
set -Eeuo pipefail

# Install and configure Nginx as the public reverse proxy for this project.
# Usage:
#   sudo bash deploy/setup-nginx.sh c3-app-178.io.vn admin@example.com
#
# The application containers are expected to expose:
#   frontend: 127.0.0.1:3000
#   backend:  127.0.0.1:8000

DOMAIN="${1:-}"
EMAIL="${2:-}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script as root or with sudo."
  exit 1
fi

if [[ -z "${DOMAIN}" || -z "${EMAIL}" ]]; then
  echo "Usage: sudo bash deploy/setup-nginx.sh DOMAIN EMAIL"
  echo "Example: sudo bash deploy/setup-nginx.sh c3-app-178.io.vn admin@example.com"
  exit 1
fi

CONFIG="/etc/nginx/sites-available/${DOMAIN}"
ENABLED_CONFIG="/etc/nginx/sites-enabled/${DOMAIN}"
BACKUP_DIR="/var/backups/nginx"

echo "==> Installing Nginx and Certbot"
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  nginx \
  certbot \
  python3-certbot-nginx

echo "==> Backing up existing site configuration, if present"
install -d -m 0755 "${BACKUP_DIR}"
if [[ -f "${CONFIG}" ]]; then
  cp -p "${CONFIG}" "${BACKUP_DIR}/${DOMAIN}.$(date +%Y%m%d%H%M%S)"
fi

echo "==> Writing HTTP reverse-proxy configuration"
install -d -m 0755 /var/www/html

cat > "${CONFIG}" <<NGINX
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

ln -sfn "${CONFIG}" "${ENABLED_CONFIG}"

echo "==> Validating and starting Nginx"
nginx -t
systemctl enable --now nginx
systemctl reload nginx

echo "==> Requesting HTTPS certificate"
certbot --nginx \
  --non-interactive \
  --agree-tos \
  --redirect \
  --email "${EMAIL}" \
  -d "${DOMAIN}"

systemctl reload nginx

echo "==> Nginx setup completed: https://${DOMAIN}"
echo "==> Certificate renewal check: certbot renew --dry-run"
