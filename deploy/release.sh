#!/usr/bin/env bash
#
# Runs ON THE VPS, piped in over SSH by .github/workflows/deploy.yml.
# Expects DEPLOY_DIR, BACKEND_IMAGE, WEB_IMAGE, REGISTRY_USER, REGISTRY_TOKEN.
#
# Swaps the running stack to the new images and verifies it actually came up.
# If it did not, the previous images are restored before this exits non-zero:
# a deploy that fails and leaves the site down is a worse outcome than one that
# fails and leaves the old version serving.

set -euo pipefail

: "${DEPLOY_DIR:?}" "${BACKEND_IMAGE:?}" "${WEB_IMAGE:?}"
: "${REGISTRY_USER:?}" "${REGISTRY_TOKEN:?}"

cd "$DEPLOY_DIR"

# The secrets files are the VPS's own and are never written by CI. Starting the
# stack without them would boot the API against dev defaults — SQLite instead
# of Postgres — and quietly serve an empty database as if it were production.
for required in backend.env web.env; do
  if [ ! -f "$required" ]; then
    echo "FATAL: $DEPLOY_DIR/$required is missing." >&2
    echo "Create it from deploy/${required}.example before the first deploy." >&2
    exit 1
  fi
done

previous_backend=""
previous_web=""
if [ -f .env ]; then
  previous_backend="$(sed -n 's/^BACKEND_IMAGE=//p' .env)"
  previous_web="$(sed -n 's/^WEB_IMAGE=//p' .env)"
fi

write_env() {
  # Only image pins live here. backend.env and web.env hold the secrets and are
  # never touched — losing those to a deploy would be unrecoverable from CI.
  cat > .env <<ENV
BACKEND_IMAGE=$1
WEB_IMAGE=$2
ENV
}

echo "$REGISTRY_TOKEN" | docker login ghcr.io -u "$REGISTRY_USER" --password-stdin

write_env "$BACKEND_IMAGE" "$WEB_IMAGE"
docker compose pull --quiet
docker compose up -d --remove-orphans

# Compose returns as soon as the containers are started, which says nothing
# about whether the app inside them works. Both images declare a HEALTHCHECK;
# this waits on that verdict.
wait_healthy() {
  local deadline=$((SECONDS + 180))
  while [ "$SECONDS" -lt "$deadline" ]; do
    local backend web
    backend="$(docker inspect --format '{{.State.Health.Status}}' boe-backend 2>/dev/null || echo missing)"
    web="$(docker inspect --format '{{.State.Health.Status}}' boe-web 2>/dev/null || echo missing)"
    case "$backend/$web" in
      healthy/healthy) return 0 ;;
      # Nothing recovers from a container that has already exited.
      unhealthy/*|*/unhealthy) echo "container reported unhealthy ($backend/$web)" >&2; return 1 ;;
    esac
    sleep 5
  done
  echo "timed out waiting for containers to report healthy" >&2
  return 1
}

if wait_healthy; then
  echo "deployed: $BACKEND_IMAGE / $WEB_IMAGE"
  # Keep the previous images so a manual rollback stays a one-liner; anything
  # older than a day of deploys is dead weight on the disk.
  docker image prune --force --filter "until=24h" >/dev/null || true
  docker logout ghcr.io >/dev/null 2>&1 || true
  exit 0
fi

echo "--- backend log tail ---" >&2
docker compose logs --tail 50 backend >&2 || true
echo "--- web log tail ---" >&2
docker compose logs --tail 50 web >&2 || true

if [ -n "$previous_backend" ] && [ -n "$previous_web" ]; then
  echo "rolling back to $previous_backend / $previous_web" >&2
  write_env "$previous_backend" "$previous_web"
  docker compose up -d --remove-orphans
  if wait_healthy; then
    echo "rolled back; the previous release is serving" >&2
  else
    echo "ROLLBACK ALSO UNHEALTHY — the site is down, needs a human" >&2
  fi
else
  # First deploy: there is no previous release to fall back to.
  echo "no previous release recorded, leaving the failed stack up for diagnosis" >&2
fi

docker logout ghcr.io >/dev/null 2>&1 || true
exit 1
