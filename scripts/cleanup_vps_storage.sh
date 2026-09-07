#!/usr/bin/env bash
# Safely reclaim disk space on a native LitReview VPS.
# Default mode is a dry run. Use --apply to perform cleanup. CI may add --yes
# to explicitly opt into the otherwise-interactive destructive cleanup, and
# --caches-only to preserve logs and rollback releases.

set -Eeuo pipefail
umask 027

APP_DIR="${APP_DIR:-/root/P-178}"
JOURNAL_RETENTION="${JOURNAL_RETENTION:-7d}"
JOURNAL_MAX_SIZE="${JOURNAL_MAX_SIZE:-500M}"
FRONTEND_RELEASES_DIR="${APP_DIR}/frontend/.deploy/releases"

APPLY=0
NON_INTERACTIVE=0
CACHES_ONLY=0
for arg in "$@"; do
    case "$arg" in
        --apply) APPLY=1 ;;
        --dry-run) APPLY=0 ;;
        --yes) NON_INTERACTIVE=1 ;;
        --caches-only) CACHES_ONLY=1 ;;
        *)
            printf 'Usage: %s [--dry-run|--apply] [--yes] [--caches-only]\n' "$0"
            exit 2
            ;;
    esac
done

if (( NON_INTERACTIVE && ! APPLY )); then
    printf '%s\n' '--yes requires --apply.' >&2
    exit 2
fi

if [[ "${EUID}" -ne 0 ]]; then
    SUDO="sudo"
else
    SUDO=""
fi

run() {
    if (( APPLY )); then
        "$@"
    else
        printf '[dry-run]'
        printf ' %q' "$@"
        printf '\n'
    fi
}

show_size() {
    local path="$1"
    if [[ -e "$path" ]]; then
        du -sh "$path" 2>/dev/null || true
    fi
}

printf 'VPS storage cleanup\n'
printf 'APP_DIR: %s\n' "$APP_DIR"
printf 'Mode: %s\n\n' "$([[ $APPLY -eq 1 ]] && echo APPLY || echo DRY-RUN)"

printf '%s\n' '--- Before ---'
df -h / || true
printf '\nLargest application logs/cache directories:\n'
show_size "${APP_DIR}/logs"
show_size "${APP_DIR}/frontend/.next/cache"
show_size "${APP_DIR}/frontend/node_modules/.cache"
show_size "${APP_DIR}/frontend/.deploy/releases"
printf '\n'

if (( APPLY && ! NON_INTERACTIVE )); then
    read -r -p 'This will delete caches, old logs, and old frontend releases. Continue? [y/N] ' answer
    [[ "$answer" =~ ^[Yy]$ ]] || { echo 'Cancelled.'; exit 0; }
fi

# Package-manager caches.
run $SUDO apt-get clean
run $SUDO rm -rf /var/lib/apt/lists/*

# Python/Node build caches are safe to recreate.
run rm -rf "${APP_DIR}/frontend/.next/cache"
run rm -rf "${APP_DIR}/frontend/node_modules/.cache"
run rm -rf "${HOME:-/root}/.cache/pip"
run rm -rf "${HOME:-/root}/.npm/_cacache"

if (( CACHES_ONLY )); then
    printf '%s\n' 'Preserved logs and frontend rollback releases (--caches-only).'
    exit 0
fi

# Unused packages, logs, and old releases are part of a full manual storage cleanup.
run $SUDO apt-get autoremove -y
run $SUDO journalctl --vacuum-time="$JOURNAL_RETENTION"
run $SUDO journalctl --vacuum-size="$JOURNAL_MAX_SIZE"
for logfile in backend.log worker.log frontend.log qdrant.log; do
    run $SUDO truncate -s 0 "${APP_DIR}/logs/${logfile}"
done

# Keep only the current and previous frontend release symlink targets.
if [[ -d "$FRONTEND_RELEASES_DIR" ]]; then
    current=""
    previous=""
    [[ -L "${APP_DIR}/frontend/.deploy/current" ]] && current="$(readlink -f "${APP_DIR}/frontend/.deploy/current" || true)"
    [[ -L "${APP_DIR}/frontend/.deploy/previous" ]] && previous="$(readlink -f "${APP_DIR}/frontend/.deploy/previous" || true)"
    while IFS= read -r -d '' release; do
        if [[ "$release" != "$current" && "$release" != "$previous" ]]; then
            run rm -rf "$release"
        fi
    done < <(find "$FRONTEND_RELEASES_DIR" -mindepth 1 -maxdepth 1 -type d -print0)
fi

printf '\n%s\n' '--- After / current view ---'
df -h / || true
if (( ! APPLY )); then
    printf '\nDry run only. Run with --apply to perform cleanup.\n'
fi
