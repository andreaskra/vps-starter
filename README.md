# VPS Starter Kit

Everything you need to host a real website **and** a real app on your own
server: a polished demo landing page, a scheduled lead-research tool with a
web dashboard, nginx, and one-click domain + https setup.

This kit accompanies the guide:
**[How to host your websites and apps on a VPS](https://andreaskra.com/guides/vps-hosting.html)**
— read that for the full walkthrough (also in German:
**[Websites und Apps auf einem VPS hosten](https://andreaskra.com/de/anleitungen/vps-hosting.html)**).
This README is the condensed version.

## Deploy with Claude Code (recommended — no terminal needed)

1. Get the kit — clone this repo, or on GitHub click **Code → Download ZIP** and
   unzip it — and open the folder in [Claude Code](https://claude.com/claude-code).
2. Say: **"Deploy this project to my server at `<your-server-ip>`."**
3. Claude asks for your server's root password and a dashboard password of
   your choice, then handles everything — SSH access, uploading the project,
   installing Docker, starting the stack, and verifying it's live.
   (The runbook it follows is in `CLAUDE.md`.)

## Manual quick start (fresh Ubuntu 24.04 VPS)

Prefer doing it yourself? Open your server's terminal and run:

```bash
git clone https://github.com/andreaskra/vps-starter.git
cd vps-starter
bash setup.sh
```

(No git on the server? `apt install -y git` first.)

The installer sets up Docker, asks you to choose a dashboard password
(or takes it non-interactively via `DASHBOARD_PASSWORD=… bash setup.sh`), and
starts everything. Either way, then open:

- `http://<your-server-ip>` — the **dashboard** (password-protected)
- `http://<your-server-ip>:8080` — the **landing page**, live on the internet

## What's inside

| Piece | What it does |
|---|---|
| `nginx/` | The front door — routes visitors to the right container, serves https once a domain is connected |
| `landing-page/` | A complete one-page website for a fictional salon business ("Chairside") — swap in your own content |
| `leadfinder/` | The lead-research app: nightly, it turns your ideal-customer description into web searches (Tavily), scores what it finds (Claude), and delivers leads to the dashboard + your Notion database |
| `setup.sh` | One-command installer for the server |
| `run-local.sh` | Runs the whole stack on your own computer in demo mode (no API costs) |

## Configure the lead finder

Everything happens in the dashboard — **Settings**:

1. **Tavily API key** — free account at [tavily.com](https://tavily.com); the free tier covers a nightly run.
2. **Anthropic API key** — from [console.anthropic.com](https://console.anthropic.com); Claude writes the searches and scores each lead.
3. **Notion** — create an integration at [notion.so/my-integrations](https://www.notion.so/my-integrations), share a page with it (page → ⋯ → Connections), and paste the integration token + the page link into Settings. A "Leads" database is created under that page on the first run.
4. Describe your **ideal customer** in plain language and pick the nightly run hour.

Press **Run now** on the Leads page to watch it work immediately.

## Connect a domain

1. At your registrar, create A records: `@` → your server IP and `www` → your server IP.
2. Dashboard → **Domains** → type the domain → **Connect**.

The kit verifies DNS, fetches a Let's Encrypt certificate, configures nginx,
and renews the certificate automatically. Your landing page is then served at
`https://yourdomain.com`.

## Run it locally (development / demo)

With Docker Desktop installed:

```bash
bash run-local.sh
```

Dashboard at `http://localhost:8090` (password `local-dev-password`), landing
page at `http://localhost:8091`. Local mode forces `DRY_RUN=1`: runs fabricate
demo leads and never call a paid API. Domain connection can't complete locally
(Let's Encrypt must reach your server from the internet) — test that part on
the real VPS.

## Hosting more sites

The kit isn't limited to one website. Each additional site is a folder + a
compose service + an nginx upstream, and can get its own preview port and its
own domain. The full step-by-step recipe lives in **`CLAUDE.md`** — written so
you can also just open this folder with an AI coding assistant (Claude Code)
and say *"add another landing page called X and put it on port 8081"*; the
assistant reads that file and knows exactly how this project fits together.

## Security notes — read once

- **The dashboard runs over plain HTTP until you connect a domain.** The
  password login and rate limiting protect access, but the API keys you paste
  travel unencrypted that one time. Connect your domain early, or paste keys
  only from a trusted network.
- **The dashboard container mounts the Docker socket** (`/var/run/docker.sock`)
  so it can fetch certificates and reload nginx for you. Anyone who gets into
  that container effectively controls the server. That's an intentional,
  documented trade-off for a single-purpose starter VPS where this dashboard is
  the only admin surface. If you harden later, look at `tecnativa/docker-socket-proxy`.
- **Keys stay on your server** — settings live in a local SQLite database in
  `leadfinder/data/`, never in git (see `.gitignore`) and never sent anywhere
  except to the services they belong to.
- Update the server monthly: `apt update && apt upgrade -y`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Dashboard not loading | `docker compose ps` — all three services should be "running". `docker compose logs leadfinder` shows errors. |
| "Wrong password" but you're sure | `bash setup.sh --reset-password` |
| Domain connect says DNS doesn't point here | A records take a few minutes to spread. Check with `ping yourdomain.com` — it should answer from your server IP. |
| Certificate request failed | Port 80 must be reachable from the internet (check your provider's firewall) and the DNS check must pass first. |
| Start over completely | `docker compose down -v && rm -rf leadfinder/data/* && bash setup.sh` |

## License

MIT — use it, modify it, ship it. See `LICENSE`.
