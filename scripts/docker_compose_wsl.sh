#!/usr/bin/env bash
# Run Docker Compose from WSL with the Docker Desktop socket group detected at runtime.

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
DOCKER_SOCKET="${DOCKER_SOCKET:-/var/run/docker.sock}"

if [[ ! -S "${DOCKER_SOCKET}" ]]; then
    printf '%s\n' \
        '[wsl-compose] Docker socket is unavailable.' \
        '[wsl-compose] In Docker Desktop, enable Resources > WSL Integration > Ubuntu, then restart Docker Desktop.' >&2
    exit 1
fi

if [[ "${APP_DIR}" == /mnt/* ]]; then
    printf '%s\n' \
        "[wsl-compose] WARNING: ${APP_DIR} is on a Windows-mounted drive." \
        '[wsl-compose] Docker builds can fail on Windows ACL/xattr. Prefer a clone under ~/P-178-wsl.' >&2
fi

export SANDBOX_DOCKER_GID
SANDBOX_DOCKER_GID="$(stat -c '%g' "${DOCKER_SOCKET}")"

printf '[wsl-compose] app=%s docker_gid=%s\n' "${APP_DIR}" "${SANDBOX_DOCKER_GID}"
exec docker compose --project-directory "${APP_DIR}" -f "${APP_DIR}/docker-compose.yml" "$@"
