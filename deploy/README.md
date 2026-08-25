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

### 4. nginx

The stack publishes on loopback only — `127.0.0.1:3000` (web) and
`127.0.0.1:8000` (API) — so the VPS's existing nginx keeps terminating TLS and
proxying, unchanged. Nothing here is exposed to the internet directly.

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

**The database is not in this stack.** `DATABASE_URL` points at the existing
managed Postgres, where the app's tables live in the `boe` schema
(`finclone/db.py` treats `public` as the legacy DCF app's). A Postgres
container here would have pointed production at an empty database and orphaned
the real one.

**Pipeline jobs are not deployed by this.** The filing monitor, crossref
sweeps, KPI sweeps and triage runs are batch entrypoints, not services. Run
them against the backend container:

```bash
docker compose exec backend python -m finclone.pipeline.monitor
docker compose exec backend python -m finclone.pipeline.crossref AAPL
```

Schedule with cron on the VPS if they should run unattended. They are
deliberately not in compose: `restart: unless-stopped` on a batch job that
exits successfully is a restart loop, and the LLM sweeps cost real money per
run.

**Schema changes apply themselves, and only additively.** The API calls
`init_db()` on startup, which is `create_all` — it creates missing tables but
never alters an existing one. A column added to a model will not appear on a
table that already exists; that needs a migration run by hand.
