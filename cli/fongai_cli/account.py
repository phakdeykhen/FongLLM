"""Sign the terminal in to a FongAI account (no API key to copy).

  fong login     shows a code, opens the browser; sign in there and click Connect
  fong logout    ends this terminal's session
  fong whoami    shows which account the terminal uses
"""
import json
import time
import urllib.error
import urllib.request
import webbrowser

LOCAL_SERVER = "http://localhost:8000/v1"


def server_root(base_url):
    """'https://fong.example.com/v1' -> 'https://fong.example.com'."""
    url = base_url.rstrip("/")
    return url[:-3] if url.endswith("/v1") else url


def _call(url, body=None, token="", method=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method or ("POST" if data is not None else "GET"),
                                 headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode()).get("detail")
        except (ValueError, AttributeError):
            msg = None
        raise RuntimeError(msg or f"{e.code} {e.reason}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"Can't reach {url.split('/api')[0]} ({e.reason}). Is the FongAI server running?") from None


def login(cfg, say):
    """Returns the updated config (token saved as api_key) or None."""
    if ":11434" in cfg["base_url"]:   # pointing straight at Ollama: sign in to the FongAI server instead
        cfg["base_url"] = LOCAL_SERVER
    root = server_root(cfg["base_url"])
    start = _call(f"{root}/api/auth/device/start", {})
    say(f"\nYour code:  {start['user_code']}\n")
    say(f"Opening {start['verify_url']}")
    say("Sign in there and click Connect. (If the browser didn't open, copy that link into it.)\n")
    try:
        webbrowser.open(start["verify_url"])
    except Exception:   # noqa: BLE001  (no browser, e.g. over SSH: the link is printed above)
        pass
    deadline = time.time() + start.get("expires_in", 600)
    while time.time() < deadline:
        time.sleep(start.get("interval", 3))
        r = _call(f"{root}/api/auth/device/poll", {"device_code": start["device_code"]})
        if r["status"] == "ok":
            cfg["api_key"] = r["token"]
            cfg["account"] = f"{r['user']['name']} <{r['user'].get('email') or r['user'].get('phone') or ''}>"
            return cfg
        if r["status"] == "expired":
            break
    say("The code expired. Run  fong login  again.")
    return None


def logout(cfg):
    if cfg.get("api_key"):
        try:
            _call(f"{server_root(cfg['base_url'])}/api/auth/logout", {}, cfg["api_key"])
        except RuntimeError:
            pass   # server unreachable: forgetting the token here is still a sign-out for this computer
    cfg["api_key"], cfg["account"] = "", ""
    return cfg


def whoami(cfg):
    if not cfg.get("api_key"):
        return None
    return _call(f"{server_root(cfg['base_url'])}/api/auth/me", token=cfg["api_key"])["user"]
