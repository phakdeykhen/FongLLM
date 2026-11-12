# FongAI web UI (React)

Claude-style chat UI for FongAI. React talks to the FastAPI backend in `server/api.py`,
which runs the same models and tools as `app/app.py` (Mistral via Ollama, FongAI 64M,
Whisper voice input, mxbai document search, image/video generation).

## Run

```bash
cd ~/Documents/FongAI && source .venv/bin/activate
uvicorn server.api:app --port 8000          # backend

cd web && npm install && npm run build      # once, or after UI changes
open http://localhost:8000                  # backend serves the built UI
```

While editing the UI, run `npm run dev` in `web/` and open http://localhost:5173
(hot reload; API calls are forwarded to :8000).

## Structure

| Path | What it does |
| --- | --- |
| `src/App.jsx` | Pages, chats (saved in the browser's localStorage), settings, streaming |
| `src/components/Sidebar.jsx` | New chat, Search, Home, Images, Videos, Documents, Settings, Recents |
| `src/components/Composer.jsx` | Message box: + attach (docs / audio), model picker, mic, send / stop |
| `src/components/ChatView.jsx` | User bubbles, Markdown answers, sources, generated media |
| `src/components/Pages.jsx` | Search, Images/Videos gallery, Documents, Settings pages |
| `src/api.js` | Calls to `/api/*`; `/api/chat` streams NDJSON events |
| `src/recorder.js` | Microphone to 16 kHz WAV (no ffmpeg needed) |
