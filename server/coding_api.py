"""OpenAI-compatible endpoint for the `fong` CLI, so users don't need Ollama on their own computer.

  POST /v1/chat/completions   forwarded to Ollama with the Fong AI model (streaming + tool calls)
  GET  /v1/models             the model users can pick

Access: every request needs "Authorization: Bearer <key>". Keys live one per line in
~/.fongai/server_keys.txt as "<key> <name>" (or in env FONG_API_KEYS="key1,key2").
With no keys set, only this computer (localhost) may connect.

Make a key for a user:   python -m server.coding_api new-key alice
List / remove keys:      python -m server.coding_api list | remove <key or name>
"""
import os
import secrets
import sys

import requests
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
FONG_MODEL = os.environ.get("FONG_MODEL", "fongai")
PUBLIC_MODELS = {"fongai": FONG_MODEL}   # name users send -> Ollama model on this server
KEYS_FILE = os.environ.get("FONG_KEYS_FILE", os.path.join(os.path.expanduser("~"), ".fongai", "server_keys.txt"))
MAX_TOKENS = int(os.environ.get("FONG_MAX_TOKENS", "4096"))   # per reply, so one user can't hold the GPU forever

router = APIRouter()


def load_keys():
    """{key: name} from the keys file and FONG_API_KEYS. Read each time, so new keys work without a restart."""
    keys = {k.strip(): "env" for k in os.environ.get("FONG_API_KEYS", "").split(",") if k.strip()}
    try:
        with open(KEYS_FILE, encoding="utf-8") as f:
            for line in f:
                parts = line.split(None, 1)
                if parts and not parts[0].startswith("#"):
                    keys[parts[0]] = parts[1].strip() if len(parts) > 1 else ""
    except OSError:
        pass
    return keys


def _error(status, message, kind="invalid_request_error"):
    return JSONResponse({"error": {"message": message, "type": kind}}, status_code=status)


def check_access(request: Request):
    """None if allowed, else an error response. A signed-in FongAI account (fong login) is always enough;
    admin keys from the keys file still work too."""
    from server import auth_api   # here, not at the top: api.py imports this module first
    if auth_api.user_from_token(request.headers.get("authorization", "")) is not None:
        return None
    keys = load_keys()
    if not keys:
        host = request.client.host if request.client else ""
        if host in ("127.0.0.1", "::1", "localhost"):
            return None
        return _error(401, "Sign in first: run  fong login", "authentication_error")
    auth = request.headers.get("authorization", "")
    key = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if key and any(secrets.compare_digest(key, k) for k in keys):
        return None
    return _error(401, "You're signed out or your session expired. Run:  fong login", "authentication_error")


@router.get("/v1/models")
def models(request: Request):
    denied = check_access(request)
    if denied:
        return denied
    return {"object": "list", "data": [{"id": m, "object": "model", "owned_by": "fongai"} for m in PUBLIC_MODELS]}


@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    denied = check_access(request)
    if denied:
        return denied
    try:
        body = await request.json()
    except ValueError:
        return _error(400, "Body must be JSON.")
    if not isinstance(body.get("messages"), list):
        return _error(400, "messages must be a list.")
    name = body.get("model") or "fongai"
    if name not in PUBLIC_MODELS:
        return _error(404, f"Unknown model '{name}'. Available: {', '.join(PUBLIC_MODELS)}")
    body["model"] = PUBLIC_MODELS[name]
    body["max_tokens"] = min(int(body.get("max_tokens") or MAX_TOKENS), MAX_TOKENS)
    stream = bool(body.get("stream"))
    try:
        upstream = await run_in_threadpool(   # don't block other users while waiting
            requests.post, f"{OLLAMA_URL}/v1/chat/completions", json=body, stream=stream, timeout=(10, 600))
    except requests.RequestException:
        return _error(503, "The Fong AI model is not running on the server. Try again later.", "server_error")
    if upstream.status_code != 200 or not stream:
        data = await run_in_threadpool(_read_json, upstream)
        if isinstance(data, dict) and data.get("model"):
            data["model"] = name   # don't expose the internal model name
        return JSONResponse(data, status_code=upstream.status_code)

    def relay():
        try:
            for chunk in upstream.iter_content(chunk_size=None):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    return StreamingResponse(relay(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _read_json(resp):
    try:
        return resp.json()
    except ValueError:
        return {"error": {"message": resp.text[:500], "type": "server_error"}}
    finally:
        resp.close()


def _cli(argv):
    cmd = argv[0] if argv else "help"
    if cmd == "new-key":
        name = " ".join(argv[1:]) or "user"
        key = "fong-" + secrets.token_urlsafe(24)
        os.makedirs(os.path.dirname(KEYS_FILE), exist_ok=True)
        with open(KEYS_FILE, "a", encoding="utf-8") as f:
            f.write(f"{key} {name}\n")
        if os.name != "nt":
            os.chmod(KEYS_FILE, 0o600)
        print(f"New key for {name}:\n  {key}\nGive it to the user. They run:  fong --api-key {key}")
    elif cmd == "list":
        for k, n in load_keys().items():
            print(f"{k[:10]}…  {n}")
    elif cmd == "remove" and len(argv) > 1:
        target = argv[1]
        try:
            with open(KEYS_FILE, encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            lines = []
        keep = [ln for ln in lines if not (ln.split() and (ln.split()[0] == target or ln.split(None, 1)[-1].strip() == target))]
        with open(KEYS_FILE, "w", encoding="utf-8") as f:
            f.writelines(keep)
        print(f"Removed {len(lines) - len(keep)} key(s).")
    else:
        print(__doc__)


if __name__ == "__main__":
    _cli(sys.argv[1:])
