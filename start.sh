#!/bin/zsh
# Start the FongAI server with the settings in .env (Google, Twilio...).  Usage: ./start.sh
cd "$(dirname "$0")"
if [[ -f .env ]]; then
  set -a; source .env; set +a   # every line in .env becomes a setting for the server
else
  echo "No .env yet: starting without Google or SMS. To add them: cp .env.example .env, then fill it in."
fi
[[ -n "$GOOGLE_CLIENT_ID" ]] && echo "Google sign-in: on" || echo "Google sign-in: off (GOOGLE_CLIENT_ID is empty)"
[[ "$FONGAI_PHONE_LOGIN" == "1" ]] && echo "Phone sign-in: on" || echo "Phone sign-in: on hold"
exec .venv/bin/uvicorn server.api:app --port "${PORT:-8000}"
