# JO AI Telegram Bot

This repository now uses one deployment path:

- GitHub repo: `ygirma315-cell/jo-ai`
- Production branch: `main`
- Hosting: one Render web service
- Frontend: served by FastAPI at `/miniapp/`
- Backend API: served by FastAPI at `/api/*`
- Telegram bot: webhook-based, handled by the same FastAPI service

## What Was Removed

- No separate Render worker
- No polling runtime
- No separate `miniapp/server.py`
- No separate `run_bot.py`
- No GitHub Pages dependency for the mini app

## Project Structure

- `main.py`: FastAPI app, mini-app hosting, health endpoints, Telegram webhook
- `bot/`: Telegram bot handlers, services, config, logging
- `miniapp/`: frontend assets served by FastAPI
- `render.yaml`: single Render blueprint

## Required Environment Variables

Copy `.env.example` to `.env` for local work.

Required:

- `BOT_TOKEN`
- `NVIDIA_API_KEY`

Optional but recommended:

- `DEEPSEEK_API_KEY`
- `KIMI_API_KEY`
- `NVIDIA_CHAT_MODEL`
- `IMAGE_MODEL`
- `DEEPSEEK_MODEL`
- `KIMI_MODEL`
- `PUBLIC_BASE_URL`
- `TELEGRAM_WEBHOOK_SECRET`

Notes:

- On Render, the app can use `RENDER_EXTERNAL_URL` automatically.
- `PUBLIC_BASE_URL` is only needed when you want to force a custom public base URL.
- The old `MINIAPP_URL` and `MINIAPP_API_BASE` flow is obsolete.

## Local Development

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the app:

```bash
python main.py
```

Local URLs:

- Mini app: `http://127.0.0.1:8000/miniapp/`
- Health: `http://127.0.0.1:8000/health`
- Runtime info: `http://127.0.0.1:8000/api/runtime-info`

Important:

- Telegram bot updates only work when the webhook URL is publicly reachable.
- For local Telegram testing, use a tunnel and set `PUBLIC_BASE_URL` or `TELEGRAM_WEBHOOK_URL`.

## Production Deploy Flow

1. Push changes to `main` on GitHub.
2. Render detects the push from `render.yaml`.
3. Render redeploys the single web service automatically.
4. The new service starts `uvicorn main:app`.
5. On startup, the app:
   - validates environment variables
   - creates the Telegram bot runtime
   - serves the mini app from `/miniapp/`
   - reconfigures the Telegram webhook
   - reconfigures the Telegram menu button
6. The bot restarts as part of the Render redeploy.

## One-Time Render Setup

In Render:

1. Open the service connected to this repo.
2. Make sure it is a `Web Service`, not a `Worker`.
3. Make sure the repo is `ygirma315-cell/jo-ai`.
4. Make sure the branch is `main`.
5. Confirm the service uses `render.yaml`.
6. Delete the old worker service if it still exists.
7. Set the required environment variables.
8. Leave auto-deploy enabled for pushes to `main`.

Recommended health check:

- `/health`

## One-Time Telegram Cleanup

The bot should now open the mini app from the same Render service.

If you previously used GitHub Pages for the mini app:

1. Remove the old `MINIAPP_URL` value from Render if it points to GitHub Pages.
2. Redeploy the Render web service.
3. Open the bot and verify the menu button opens the Render-hosted mini app.

## VS Code Git Workflow

Recommended approach:

1. Open the Source Control panel.
2. Review changed files.
3. Stage the files you want.
4. Write a commit message in the Source Control input.
5. If GitHub Copilot is installed, use commit message generation as a suggestion only.
6. Click `Commit`.
7. Click `Sync Changes`.
8. Confirm the sync when VS Code asks.

Safety choices already set in `.vscode/settings.json`:

- auto-fetch is enabled
- sync still asks for confirmation
- smart commit is disabled

## Health Endpoints

- `GET /health`
- `GET /api/health`
- `GET /uptime`
- `GET /api/uptime`
- `GET /runtime-info`
- `GET /api/runtime-info`

## CI

GitHub Actions now runs a lightweight smoke check on pushes to `main` and on pull requests:

- installs dependencies
- compiles Python sources
- imports the FastAPI app
