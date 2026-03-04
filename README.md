# Telegram AI Bot + Mini App

## Features

- Telegram bot:
  - `/chat` -> JO AI Chat
  - `/code` -> code generation
  - `/research` -> research answers
  - `/prompt` -> prompt generation
  - `/image` -> image generation flow
  - `/deepseek` -> select DeepSeek profile:
    - DeepSeek Thinking
    - DeepSeek Reasoning
  - `/kimi` -> Kimi Image Describer (send image, get description)
  - Utilities:
    - Calculator
    - Games (Tic-Tac-Toe, Guess the Number)

- Website / Mini App:
  - AI Chat / Code / Research / Prompt / Image / Kimi Image Describer
  - DeepSeek profile selector (Thinking / Reasoning)
  - API health indicator

## Removed

- Quiz feature and related files were removed from runtime and project.

## Setup

1. Install:
   ```bash
   pip install -r requirements.txt
   ```
2. Configure `.env`:
   - `BOT_TOKEN`
   - `NVIDIA_API_KEY`
   - `NVIDIA_CHAT_MODEL`
   - `DEEPSEEK_API_KEY`
   - `DEEPSEEK_MODEL`
   - `KIMI_API_KEY`
   - `KIMI_MODEL`
   - `MINIAPP_URL`
   - `MINIAPP_API_BASE` (public backend base URL serving `/api/*`)
3. Run bot:
   ```bash
   python main.py
   ```
4. Run mini app backend:
   ```bash
   python miniapp/server.py
   ```

## Mini App API

- `GET /api/health`
- `POST /api/chat`
- `POST /api/code`
- `POST /api/research`
- `POST /api/prompt`
- `POST /api/image`
- `POST /api/kimi_image_describer`

## GitHub Deploy (VS Code)

```bash
git add .
git commit -m "Update website and AI features"
git push origin main
```
