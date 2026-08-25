# Deployment

Push to `main` → tests run → images build → the VPS swaps to them. Nothing else
is manual after the one-time setup below.

```
push to main
  └─ ci.yml          pytest, tsc, next build, both Dockerfiles
     └─ build        push ghcr.io/<owner>/boe-analytics-{backend,web}:<sha>
        └─ deploy    scp compose → release.sh → health check → rollback on failure
```

Failing tests stop the deploy. A release that starts but never reports healthy
is rolled back to the previous images automatically.

## One-time setup

### 1. Secrets on the VPS

The pipeline never handles application secrets. They live in two files in the
deploy directory (`/opt/boe-analytics` by default) and CI does not read, write
or overwrite them:

```bash
sudo mkdir -p /opt/boe-analytics && cd /opt/boe-analytics
# fill both in from the .example files in this directory
sudo nano backend.env
sudo nano web.env
sudo chmod 600 backend.env web.env
```

`release.sh` refuses to start the stack if either is missing, rather than
booting the API on its dev defaults and serving an empty SQLite file as though
it were production.

### 2. A deploy key

On the VPS, for the user the pipeline will connect as:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/gh_deploy -N "" -C "github-actions"
cat ~/.ssh/gh_deploy.pub >> ~/.ssh/authorized_keys
cat ~/.ssh/gh_deploy          # the private key → VPS_SSH_KEY secret
```

That user needs to be able to run `docker` without a password prompt
(`sudo usermod -aG docker $USER`).

### 3. Repository secrets and variables

**Settings → Secrets and variables → Actions.**

| Secret | What it is |
|---|---|
| `VPS_HOST` | Hostname or IP |
| `VPS_USER` | SSH user from step 2 |
| `VPS_SSH_KEY` | Private key from step 2, whole file including header/footer |
| `VPS_KNOWN_HOSTS` | Output of `ssh-keyscan -H <host>`, run somewhere you trust |

`VPS_KNOWN_HOSTS` is required, not optional. The alternative — disabling host
key checking — hands the deploy, the registry token and a shell to anything
that can answer on that address.

| Variable | Default | What it is |
|---|---|---|
| `DEPLOY_DIR` | `/opt/boe-analytics` | Where the compose file and env files live |

No registry credentials are needed. The workflow's own scoped token is passed
through the SSH session and logged out at the end, so nothing long-lived to
pull images with is left on the VPS.

### 4. nginx — already configured, do not change it

The `analytics.boegroup.com` vhost already proxies to the ports this stack
binds, so nothing needs editing:

```
location /api/  ->  127.0.0.1:8100     (backend)
location /      ->  127.0.0.1:3200     (web)
```

Both bind loopback only, so nginx stays the sole route in and keeps terminating
TLS.

**Three apps share this VPS and one nginx.** The port numbers above are not
interchangeable:

| Port | Owner | Serves |
|---|---|---|
| 8100 / 3200 | this stack | `analytics.boegroup.com` |
| 8020 | `canalyst-clone.service` | `canalyst.boegroup.com` |
| 3000 | pm2-managed Next app | `dcf.boegroup.com`, and the bare IP |

`release.sh` refuses to deploy if a non-container process holds 8100 or 3200,
because a deploy that wins a port race would take one of the other two sites
off the air, and the rollback would not put it back.

## Rolling back

Automatic on a failed health check. To go back manually, on the VPS:

```bash
cd /opt/boe-analytics
sed -i 's/:[0-9a-f]\{40\}$/:<older-sha>/' .env
docker compose up -d
```

Any commit SHA that reached `main` has images in GHCR, so rollback targets are
whatever is still in the registry.

## Things worth knowing

**The database is not in this stack.** Postgres 17 runs on the VPS itself
(self-hosted since July 2026, replacing Supabase) and holds the live data. A
Postgres container here would have pointed production at an empty database and
orphaned the real one. Backups remain the VPS's job — nothing in this pipeline
touches or dumps it.

**Both services use host networking.** Postgres binds `127.0.0.1:5432`, and in
a bridged container `127.0.0.1` is the container itself, so every query would
fail with "connection refused". The alternative was to make Postgres listen on
the Docker bridge — widening it from loopback to a private subnet, plus
`pg_hba` and firewall changes. Sharing the host namespace instead leaves
Postgres loopback-only and untouched. The cost: `ports:` no longer applies, so
both services pin themselves to `127.0.0.1` (the backend via a `command`
override, the web tier via `HOSTNAME`). Neither is reachable except through
nginx, same as before.

**`finclone/db.py` still sets `search_path to boe, public`,** so the `boe`
schema must exist in `boe_analytics`. If it does not, Postgres falls through to
`public` and `init_db()` creates the app's tables there on first boot:

```sql
CREATE SCHEMA IF NOT EXISTS boe;
```

**Pipeline jobs are not deployed by this, and this is the one loose end.**
`boe-pipeline.service` runs `/root/boe-analytics/run_pipeline.sh` from a git
clone with its own venv and its own `backend/.env`. This pipeline never touches
that directory, so after the first deploy the API serves the image's code while
the sweeps keep running the clone's — and they drift further apart with every
push.

Two ways to close it, neither done here because both affect a running sweep:

1. Point the service at the container:
   `docker compose exec -T backend python -m finclone.pipeline...`, so image and
   sweeps share one code source.
2. Add `git -C /root/boe-analytics pull` to the deploy, accepting that it can
   change code underneath an in-flight sweep.

Ad-hoc runs against the deployed code work today:

```bash
docker compose exec backend python -m finclone.pipeline.monitor
docker compose exec backend python -m finclone.pipeline.crossref AAPL
```

Batch jobs are deliberately not compose services: `restart: unless-stopped` on
a job that exits successfully is a restart loop, and the LLM sweeps cost real
money per run.

**Schema changes apply themselves, and only additively.** The API calls
`init_db()` on startup, which is `create_all` — it creates missing tables but
never alters an existing one. A column added to a model will not appear on a
table that already exists; that needs a migration run by hand.
