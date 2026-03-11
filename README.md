# JO AI

Single production repository: `ygirma315-cell/jo-ai`

This repo now uses one codebase with two frontends and one shared backend:

- Telegram bot frontend: chat commands, menus, callbacks, and Telegram-side responses in `bot/`
- Telegram mini app frontend: static HTML/CSS/JS in `miniapp/`
- Shared backend/API: FastAPI app in `main.py`, used by both the bot and the mini app

## Hosting Model

- GitHub Pages hosts the static mini app from `miniapp/`
- Render hosts the FastAPI backend/API
- Render also runs the Telegram bot webhook runtime

Expected production URLs:

- GitHub Pages mini app: `https://ygirma315-cell.github.io/jo-ai/`
- Render backend/API: `https://jo-ai.onrender.com` if the Render service keeps the `jo-ai` hostname

If your actual Render hostname differs, update `miniapp/config.js`.

## Repository Structure

- `main.py`: shared FastAPI backend, health endpoints, API routes, Telegram webhook
- `bot/`: Telegram bot frontend logic, handlers, keyboards, services, config
- `miniapp/`: static web frontend for Telegram Mini App / browser use
- `scripts/`: safe local helper scripts for validation, mini app serving, and deploy prep
- `.vscode/`: VS Code tasks, launch config, and workspace recommendations
- `.github/workflows/ci.yml`: smoke check for Python app
- `.github/workflows/pages.yml`: deploys `miniapp/` to GitHub Pages
- `render.yaml`: Render web service blueprint for backend + bot runtime

## What Changed

- Render no longer serves the mini app files directly
- The backend root no longer redirects to `/miniapp/`
- The bot now defaults to the GitHub Pages mini app URL instead of the Render URL
- The bot now opens the exact GitHub Pages mini app URL everywhere
- `miniapp/config.js` provides the public backend base for direct browser visits to GitHub Pages
- GitHub Actions now deploys `miniapp/` to GitHub Pages from this same repo

## Local Development

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Copy `.env.example` to `.env` and fill in the required secrets:

- `BOT_TOKEN`
- `NVIDIA_API_KEY`
- `IMAGE_API_KEY` (recommended for Image Generator; falls back to `NVIDIA_API_KEY` if unset)

3. Run the backend/API:

```bash
python main.py
```

4. Serve the static mini app locally from `miniapp/`:

```bash
python scripts/serve_miniapp.py
```

Local URLs:

- Backend/API: `http://127.0.0.1:8000`
- Mini app: `http://127.0.0.1:5500`
- Health: `http://127.0.0.1:8000/api/health`
- Admin dashboard: `http://127.0.0.1:8000/admin`

For local mini app testing, either:

- keep `miniapp/config.js` pointed at `http://127.0.0.1:8000`, or
- open the page with `?api_base=http://127.0.0.1:8000`

## Safe Automation

VS Code workspace automation:

- Task: `JO AI: Validate Local Setup`
- Task: `JO AI: Validate Deployment Config`
- Task: `JO AI: Run Backend`
- Task: `JO AI: Serve Mini App`
- Task: `JO AI: Prepare Deploy`
- Launch config: `JO AI: Debug Backend`
- Launch config: `JO AI: Debug Setup Validation`

Helper scripts:

- `python scripts/validate_setup.py`: checks local env, repo structure, Pages workflow, and URL config
- `python scripts/validate_setup.py --deployment --skip-env`: checks deployment-facing config without requiring local secrets
- `python scripts/serve_miniapp.py`: serves the static mini app on `http://127.0.0.1:5500`
- `python scripts/prepare_deploy.py`: runs deploy-safe validation, compile checks, imports the app, then shows git status

These tools do not push commits or sync branches. You still review changes yourself before committing or pushing.

## Environment Variables

Required:

- `BOT_TOKEN`
- `NVIDIA_API_KEY`

Optional:

- `IMAGE_API_KEY`
- `DEEPSEEK_API_KEY`
- `KIMI_API_KEY`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY` (recommended for backend tracking writes)
- `SUPABASE_ANON_KEY` (fallback only; can be blocked by RLS)
- `SUPABASE_ALLOW_ANON_FALLBACK` (default `false`; keep disabled in production)
- `SUPABASE_DB_URL` (recommended; direct Postgres tracking backend)
- `SUPABASE_USERS_TABLE` (default: `users`)
- `SUPABASE_HISTORY_TABLE` (default: `history`)
- `PUBLIC_BASE_URL`
- `MINIAPP_URL`
- `MINIAPP_API_BASE`
- `ALLOWED_ORIGINS`
- `TELEGRAM_WEBHOOK_URL`
- `TELEGRAM_WEBHOOK_SECRET`
- `ADMIN_DASHBOARD_TOKEN` (required to unlock `/admin` and `/api/admin/*`)
- `ADMIN_DASHBOARD_OWNER_TELEGRAM_ID` (optional Telegram mini app one-tap admin login)
- `ADMIN_DASHBOARD_TELEGRAM_BOT_TOKEN` (optional; use when admin mini app login comes from a different bot token)

Defaults:

- `MINIAPP_URL` defaults to `https://ygirma315-cell.github.io/jo-ai/`
- `MINIAPP_API_BASE` defaults to Render's public backend URL when available

Important:

- Keep `MINIAPP_URL` set to `https://ygirma315-cell.github.io/jo-ai/` for a consistent Telegram mini app URL.
- For production tracking reliability on Render, set either:
  - `SUPABASE_DB_URL`, or
  - `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY`

## Deployments

### Render

Render deploys the shared backend and Telegram bot runtime from `render.yaml`.

The Render service should:

- run `uvicorn main:app --host 0.0.0.0 --port $PORT`
- expose the API and health routes
- receive Telegram webhooks at `/telegram/webhook`
- not serve the static mini app

### GitHub Pages

GitHub Pages deploys the `miniapp/` folder using `.github/workflows/pages.yml`.

The workflow:

- runs on pushes to `main` when `miniapp/` changes
- uploads `miniapp/` as the Pages artifact
- deploys the static site to `https://ygirma315-cell.github.io/jo-ai/`

## Update Flow

When you push to `main`:

- Render redeploys the backend/API + bot runtime
- GitHub Pages redeploys the static mini app if `miniapp/` changed

That keeps one repo while separating responsibilities cleanly:

- bot + API uptime concerns stay on Render
- mini app loading stays on GitHub Pages

## How To Update

Simple future workflow:

1. Make code changes in VS Code
2. Run `JO AI: Validate Local Setup`
3. If you changed mini app hosting or deployment config, run `JO AI: Validate Deployment Config`
4. Before committing, run `JO AI: Prepare Deploy`
5. Review the diff in Source Control
6. Commit manually
7. Push manually
8. Confirm Render and GitHub Pages deployments complete successfully

## Manual Setup Checklist

1. In GitHub repo settings, enable Pages with source `GitHub Actions`
2. Push this repo to `main`
3. Let `.github/workflows/pages.yml` publish `miniapp/`
4. Confirm the live Pages URL is `https://ygirma315-cell.github.io/jo-ai/`
5. Confirm the Render backend public URL
6. If the Render URL is not `https://jo-ai.onrender.com`, edit `miniapp/config.js`
7. Redeploy Render if you want `MINIAPP_URL` from `render.yaml` applied to the service environment
8. Open the Telegram bot and verify the menu button opens the GitHub Pages URL

## Secrets Hygiene

- `.env` is gitignored
- `.env.example` contains examples only
- No bot token or provider secret is stored in `miniapp/`
- `miniapp/config.js` contains only a public backend URL, not a secret
