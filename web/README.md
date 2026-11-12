# Fong AI web app (React)

Chat UI for Fong AI, built with React + Vite. It talks to the FastAPI backend in `server/api.py`,
which runs the models and tools (FongAI 3.4 / 3.2, Whisper voice input, document search, image and video generation).

## Run

Start the backend (it also serves the built UI), then open http://localhost:8000:

```bash
cd ~/Documents/FongAI
source .venv/bin/activate
uvicorn server.api:app --port 8000
```

Build the UI once, and again after changing anything in `web/src` (in a second terminal):

```bash
cd ~/Documents/FongAI/web
npm install
npm run build
```

While editing the UI, run `npm run dev` in `web/` and open http://localhost:5173 (live reload; API calls go to :8000).

## Optional: "Continue with Google"

Signing in is optional; without it everyone uses the app as a guest. To turn Google sign-in on:

1. In Google Cloud Console → APIs & Services → Credentials, create an **OAuth client ID** of type **Web application**.
2. Add `http://localhost:8000` (and `http://localhost:5173` if you use `npm run dev`) under **Authorized JavaScript origins**.
3. Start the backend with the client ID:

```bash
GOOGLE_CLIENT_ID=1234-abc.apps.googleusercontent.com uvicorn server.api:app --port 8000
```

The backend only checks the Google token and returns name, email and picture; nothing is stored on the server.

## Folder structure

```
web/
├── index.html              page shell, fonts, icons
├── vite.config.js          dev server, proxy to :8000, "@" → src alias
├── jsconfig.json           lets editors resolve "@/..." imports
├── public/                 static files copied as-is (icons, logo, login art, style samples)
│   └── styles/             sample picture for each image style
└── src/
    ├── main.jsx            entry point
    ├── App.jsx             layout: sidebar + current page, login window, lightbox
    ├── api/client.js       all calls to the backend (/api/*); chat streams NDJSON
    ├── hooks/              useChats (chats + streaming), useLocalStorage, useTheme, useShortcuts
    ├── lib/                constants, storage, format helpers, microphone recorder
    ├── components/
    │   ├── ui/             Icon (Lucide icons by short name)
    │   ├── layout/         Sidebar, ProfileMenu
    │   ├── chat/           Composer, ChatView
    │   ├── media/          MediaCard, MediaView, Lightbox
    │   └── auth/           LoginModal (Google or guest, both optional)
    ├── pages/              Home, Chat, Search, Images, Videos, Documents, Settings, Profile, Usage, Help
    └── styles/global.css   theme tokens (light + dark) and all styles
```

Conventions: one component per file, pages in `pages/`, reusable pieces in `components/<area>/`,
no relative `../` imports (use `@/`), 2-space indent, no semicolons, single quotes (see `.prettierrc.json`).
