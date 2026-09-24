# VPS Starter Kit — project reference

This file is the map of the project, written for AI coding assistants (and
curious humans). Read this before changing anything.

## What this is

A self-hosted stack for one small VPS, run entirely by Docker Compose:

```
Internet ──▶ nginx (the only container with published ports)
              ├── :80   default server  ──▶ leadfinder:8000   (dashboard, password-protected)
              ├── :8080 default server  ──▶ landing-page:80   (website preview, no domain needed)
              ├── :443  per-domain blocks in nginx/sites/*.conf ──▶ a site container
              └── /.well-known/acme-challenge/  (Let's Encrypt webroot, shared volume)
```

| Path | What it is |
|---|---|
| `docker-compose.yml` | The service list. Project name is pinned to `vps-starter` — container/volume names (`vps-starter-nginx`, `vps-starter_letsencrypt`) are referenced in code; don't rename them. |
| `docker-compose.local.yml` | Dev override: ports 8090/8091, forces `DRY_RUN=1`. |
| `nginx/nginx.conf` | Static config: upstreams + the two default servers. Loaded read-only. |
| `nginx/sites/*.conf` | **Generated at runtime** by the dashboard (one file per connected domain). Don't commit; safe to hand-edit (see "Adding a landing page"). |
| `landing-page/` | A static site: `index.html` + assets + a 4-line nginx Dockerfile. The template for every additional site. |
| `leadfinder/` | FastAPI app: dashboard UI, nightly lead research (Tavily + Anthropic + Notion), domain/certificate automation. |
| `setup.sh` | VPS installer (Docker install, password prompt, writes `.env`, `compose up`). |
| `run-local.sh` | Local dev runner (dev `.env`, DRY_RUN, alternate ports). |

Key leadfinder modules: `app/main.py` (routes + APScheduler jobs),
`app/research.py` (search pipeline), `app/llm.py` (Claude calls, structured
outputs), `app/notion.py` (Leads database), `app/domains.py` (DNS check →
certbot → nginx block → reload), `app/db.py` (SQLite in `leadfinder/data/`,
includes all user-editable settings), `app/auth.py` (PBKDF2 + signed cookie).

## Conventions and gotchas

- **Secrets**: API keys live in the SQLite settings table (entered via the
  dashboard), never in files. `.env` holds only the password hash, cookie
  secret, and deploy switches — written by `setup.sh`/`run-local.sh`.
- **`$` in `.env` values breaks silently**: docker compose interpolates `$`
  inside `env_file` values. That's why the password hash format is
  colon-delimited (`pbkdf2_sha256:iterations:salt:hash`). Never write a value
  containing `$` into `.env`.
- **docker.sock**: the leadfinder container controls the host Docker daemon
  (runs certbot as a sibling container, HUPs nginx). Treat any code running in
  that container as root on the host.
- **DRY_RUN=1** fabricates lead results and skips every paid API call — always
  develop and test in this mode (`run-local.sh` sets it).
- After changing nginx config: `docker compose exec nginx nginx -t` then
  `docker compose kill -s HUP nginx` (HUP keeps the old config if the new one
  is invalid). After changing a site's files or any Dockerfile:
  `docker compose up -d --build <service>`.

## Adding another landing page (the common request)

Every extra website is: a folder, a compose service, an nginx upstream, and a
route (a preview port and/or a domain). Example for a site called `portfolio`:

**1. Create the site folder** — copy the pattern of `landing-page/`:

```
portfolio/
├── Dockerfile      # identical 4-liner: FROM nginx:alpine / COPY . /usr/share/nginx/html/
├── index.html
└── (css/js/assets)
```

**2. Register the container** — in `docker-compose.yml`, next to `landing-page`:

```yaml
  portfolio:
    build: ./portfolio
    container_name: vps-starter-portfolio
    restart: unless-stopped
```

Also add `portfolio` to the nginx service's `depends_on` list.

**3. Register the upstream** — in `nginx/nginx.conf`, next to `landing_backend`:

```nginx
    upstream portfolio_backend {
        server portfolio:80;
    }
```

**4a. Reach it without a domain (preview port)** — add a server block in
`nginx/nginx.conf` (pick the next free port, 8081, 8082, …):

```nginx
    server {
        listen 8081 default_server;
        server_name _;
        location / {
            proxy_pass http://portfolio_backend;
            proxy_set_header Host $host;
        }
    }
```

…and publish the port on the nginx service in `docker-compose.yml`
(`- "8081:8081"`). If ufw is active on the server: `ufw allow 8081/tcp`.
Then `docker compose up -d --build` → `http://<server-ip>:8081`.

**4b. Connect its own domain** — the dashboard's Domains page always targets
`landing_backend`, so for additional sites finish by hand:

1. Point the domain's A records (`@` and `www`) at the server IP.
2. Connect the domain in the dashboard as usual (DNS check + certificate +
   generated config all still apply).
3. Edit the generated `nginx/sites/<domain>.conf`: in the `listen 443 ssl`
   block, change `proxy_pass http://landing_backend;` to
   `proxy_pass http://portfolio_backend;`.
4. Reload: `docker compose kill -s HUP nginx`.

The file survives dashboard restarts (it only rewrites a domain's conf when
that domain is re-connected), and certificate renewal is independent of which
upstream the domain proxies to.

**Non-static sites** (an app with its own server) work the same way — the only
differences are the Dockerfile and the upstream port (`server myapp:3000;`).

## Deploying this project to a VPS (agent runbook)

Users are told to open this folder in Claude Code and ask for a deployment.
When asked to deploy, follow this runbook.

**Collect from the user (ask, don't guess):**
1. The server's IP address (from their VPS provider's panel).
2. Root access — their root password, or confirmation that an SSH key is
   already installed.
3. A dashboard password of their choice (min 8 characters).

Never echo passwords back, never write them to any file that persists, and
never commit them.

**1. Establish SSH access** (target: key-based, non-interactive):

```bash
ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new root@<IP> true
```

If that fails (password-only server): generate a key if the user has none
(`ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519`), then install it. macOS
and most Linux ship `expect` — use it to feed the root password to
`ssh-copy-id` once, from a temp script that is deleted immediately afterwards:

```bash
expect -c 'spawn ssh-copy-id -o StrictHostKeyChecking=accept-new root@<IP>
expect "assword:" { send "<ROOT_PASSWORD>\r" }
expect eof' && history -c 2>/dev/null || true
```

(If `expect` is unavailable, ask the user to run
`ssh-copy-id root@<IP>` in their own terminal and type the password once —
that is the only acceptable manual fallback.)

**2. Upload the project** (from this folder):

```bash
rsync -az --delete \
  --exclude .env --exclude 'leadfinder/data/*' --exclude 'nginx/sites/*.conf' \
  ./ root@<IP>:/opt/vps-starter/
```

(`--exclude .env` keeps any local dev credentials off the server and protects
an existing server `.env` from `--delete`.)

**3. Run the installer non-interactively** — `setup.sh` accepts the dashboard
password via environment variable:

```bash
ssh root@<IP> "cd /opt/vps-starter && DASHBOARD_PASSWORD='<their choice>' bash setup.sh"
```

This installs Docker if missing, writes `.env` (password hash, secret key,
public IP), opens firewall ports if ufw is active, and starts the stack.
Takes 2–3 minutes on first run.

**4. Verify before reporting success:**

```bash
curl -s -o /dev/null -w '%{http_code}' http://<IP>/login      # expect 200
curl -s -o /dev/null -w '%{http_code}' http://<IP>:8080/      # expect 200
```

**5. Report to the user:** the dashboard URL (`http://<IP>`), the landing page
URL (`http://<IP>:8080`), and the next step — log in and fill in the three API
keys under Settings (the dashboard explains where each key comes from).

**Redeploy after local changes:** repeat step 2, then
`ssh root@<IP> "cd /opt/vps-starter && docker compose up -d --build"`.

**Server maintenance** ("update my server"):
`ssh root@<IP> "apt-get update -q && apt-get upgrade -y -q"` — report what was
upgraded.

## Testing checklist before shipping a change

```bash
bash run-local.sh                      # builds + starts in DRY_RUN on :8090/:8091
python3 -m py_compile leadfinder/app/*.py
docker compose -p vps-starter exec nginx nginx -t
# dashboard: log in (local-dev-password), save Settings, Run now, check Leads/CSV
docker compose -p vps-starter down     # when done
```
