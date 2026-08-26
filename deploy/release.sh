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

# Ports from the analytics.boegroup.com nginx vhost:
#   location /api/  ->  127.0.0.1:8100
#   location /      ->  127.0.0.1:3200
API_PORT=8100
WEB_PORT=3200

cd "$DEPLOY_DIR"

# The secrets files are the VPS's own and are never written by CI. Starting the
# stack without them would boot the API against dev defaults -- SQLite instead
# of Postgres -- and quietly serve an empty database as if it were production.
for required in backend.env web.env; do
  if [ ! -f "$required" ]; then
    echo "FATAL: $DEPLOY_DIR/$required is missing." >&2
    echo "Create it from deploy/${required}.example before the first deploy." >&2
    exit 1
  fi
done

# This VPS runs three apps behind one nginx: canalyst-clone.service holds 8020
# and the pm2-managed DCF app holds 3000. Ours are 8100 and 3200. If anything
# other than our own containers has taken one of those, stop rather than fight
# for it -- a deploy that wins a port race takes an unrelated working site off
# the air, and the rollback below would not put it back.
check_port_free() {
  local port="$1" pids pid cgroup
  # The `|| true` is load-bearing. grep exits 1 when it matches nothing, which
  # under `set -o pipefail` fails the whole pipeline and, under `set -e`, kills
  # the script at this assignment -- silently, before it prints anything. A free
  # port is the normal case, so without this the guard let the deploy through
  # only when a port was already taken: exactly backwards.
  pids="$(ss -tlnp "sport = :$port" 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u || true)"
  [ -z "$pids" ] && return 0

  for pid in $pids; do
    cgroup="$(cat "/proc/$pid/cgroup" 2>/dev/null || true)"
    # Our own containers holding the port is the normal steady state after the
    # first deploy: compose replaces them in place.
    case "$cgroup" in
      *docker*|*containerd*) continue ;;
    esac
    echo "FATAL: port $port is held by a non-container process (pid $pid):" >&2
    tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null >&2 || true
    echo >&2
    echo "Refusing to deploy. 8100/3200 are BOE Analytics; 8020 is" >&2
    echo "canalyst-clone.service and 3000 is the pm2 DCF app." >&2
    exit 1
  done
}

check_port_free "$API_PORT"
check_port_free "$WEB_PORT"

previous_backend=""
previous_web=""
if [ -f .env ]; then
  previous_backend="$(sed -n 's/^BACKEND_IMAGE=//p' .env)"
  previous_web="$(sed -n 's/^WEB_IMAGE=//p' .env)"
fi

write_env() {
  # Only image pins live here. backend.env and web.env hold the secrets and are
  # never touched -- losing those to a deploy would be unrecoverable from CI.
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
  local deadline=$((SECONDS + 180)) backend web
  while [ "$SECONDS" -lt "$deadline" ]; do
    backend="$(docker inspect --format '{{.State.Health.Status}}' boe-backend 2>/dev/null || echo missing)"
    web="$(docker inspect --format '{{.State.Health.Status}}' boe-web 2>/dev/null || echo missing)"
    case "$backend/$web" in
      healthy/healthy) return 0 ;;
      unhealthy/*|*/unhealthy)
        echo "container reported unhealthy ($backend/$web)" >&2
        return 1 ;;
    esac
    sleep 5
  done
  echo "timed out waiting for containers to report healthy" >&2
  return 1
}

if wait_healthy; then
  echo "deployed: $BACKEND_IMAGE / $WEB_IMAGE"
  # The healthcheck proves the app answers inside the container. This proves it
  # answers on the interface nginx actually proxies to, which is a different
  # claim and the one that decides whether the site is up.
  curl -fsS --max-time 10 "http://127.0.0.1:${API_PORT}/health" >/dev/null \
    && echo "  api  127.0.0.1:${API_PORT} ok" \
    || echo "  WARNING: nothing answering on 127.0.0.1:${API_PORT} (nginx /api/ will 502)" >&2
  curl -fsS --max-time 10 -o /dev/null "http://127.0.0.1:${WEB_PORT}/" \
    && echo "  web  127.0.0.1:${WEB_PORT} ok" \
    || echo "  WARNING: nothing answering on 127.0.0.1:${WEB_PORT} (nginx / will 502)" >&2
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
    echo "ROLLBACK ALSO UNHEALTHY -- the site is down, needs a human" >&2
  fi
else
  # First deploy: there is no previous release to fall back to.
  echo "no previous release recorded, leaving the failed stack up for diagnosis" >&2
fi

docker logout ghcr.io >/dev/null 2>&1 || true
exit 1
