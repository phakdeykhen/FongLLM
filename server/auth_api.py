"""
FongAI accounts: sign up / sign in with email and password, or with Google. Stored in SQLite (out/fongai.db).

- passwords: scrypt (Python's hashlib) with a random salt per user, compared in constant time
- sessions: a random token given to the browser; only its SHA-256 is stored, valid 30 days
- the browser sends it as "Authorization: Bearer <token>"

  POST /api/auth/signup   {name, email, password}  -> {user, token}
  POST /api/auth/login    {email, password}        -> {user, token}
  GET  /api/auth/me                                -> {user}
  POST /api/auth/logout                            -> {ok}
  POST /api/auth/phone/send    {phone}              -> {sent, test_code?}   6-digit code by SMS (Twilio), 5 minutes
  POST /api/auth/phone/verify  {phone, code}        -> {user, token}        signs in, or creates the account
SMS: set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM. Without them, test mode: the code is returned to the
browser, but ONLY for requests from this computer (127.0.0.1), so nobody outside can sign in as any number.
Google sign-in (/api/auth/google in server/api.py) calls google_user() to create or find the account.
"""
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
import time

import requests
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH = os.environ.get("FONGAI_DB", os.path.join(ROOT, "out", "fongai.db"))
SESSION_DAYS = 30
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

router = APIRouter()
_lock = threading.Lock()


def _db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, email TEXT UNIQUE, name TEXT NOT NULL,
            password_hash TEXT, google_sub TEXT UNIQUE, picture TEXT, created REAL NOT NULL, phone TEXT UNIQUE);
        CREATE TABLE IF NOT EXISTS phone_codes (
            phone TEXT PRIMARY KEY, code_hash TEXT NOT NULL, expires REAL NOT NULL, tries INTEGER NOT NULL DEFAULT 0,
            sent_at REAL NOT NULL, sends_hour INTEGER NOT NULL DEFAULT 1, hour_start REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created REAL NOT NULL, expires REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
        CREATE TABLE IF NOT EXISTS device_logins (
            device_hash TEXT PRIMARY KEY, user_code TEXT UNIQUE NOT NULL, expires REAL NOT NULL,
            user_id TEXT, done INTEGER NOT NULL DEFAULT 0);
    """)
    if "phone" not in [r["name"] for r in con.execute("PRAGMA table_info(users)")]:   # older database
        con.execute("ALTER TABLE users ADD COLUMN phone TEXT")
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_phone ON users(phone)")
    return con


_con = None


def db():
    global _con
    if _con is None:
        _con = _db()
    return _con


# ---------- passwords and tokens ----------
def hash_password(password):
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${key.hex()}"


def check_password(password, stored):
    try:
        _, salt, key = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(got.hex(), key)
    except (ValueError, AttributeError):
        return False


def _token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def new_session(user_id):
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _lock:
        db().execute("INSERT INTO sessions VALUES (?, ?, ?, ?)", (_token_hash(token), user_id, now, now + SESSION_DAYS * 86400))
        db().execute("DELETE FROM sessions WHERE expires < ?", (now,))
        db().commit()
    return token


def public(row):
    provider = "email" if row["password_hash"] else "google" if row["google_sub"] else "phone"
    return {"id": row["id"], "name": row["name"], "email": row["email"], "phone": row["phone"], "picture": row["picture"],
            "provider": provider, "created": row["created"]}


def user_from_token(authorization):
    """The signed-in user for an 'Authorization: Bearer <token>' header, or None."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    th = _token_hash(authorization.split(None, 1)[1].strip())
    row = db().execute("SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ? AND s.expires > ?",
                       (th, time.time())).fetchone()
    return row


# ---------- endpoints ----------
class SignUp(BaseModel):
    name: str
    email: str
    password: str


class SignIn(BaseModel):
    email: str
    password: str


@router.post("/api/auth/signup")
def signup(body: SignUp):
    name, email = body.name.strip()[:40], body.email.strip().lower()
    if not name:
        raise HTTPException(400, "Please enter your name.")
    if not EMAIL.match(email):
        raise HTTPException(400, "Please enter a valid email address.")
    if len(body.password) < 8:
        raise HTTPException(400, "Use a password with at least 8 characters.")
    with _lock:
        if db().execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            raise HTTPException(409, "An account with this email already exists. Sign in instead.")
        uid = secrets.token_hex(8)
        db().execute("INSERT INTO users (id, email, name, password_hash, created) VALUES (?, ?, ?, ?, ?)",
                     (uid, email, name, hash_password(body.password), time.time()))
        db().commit()
    row = db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    return {"user": public(row), "token": new_session(uid)}


@router.post("/api/auth/login")
def login(body: SignIn):
    email = body.email.strip().lower()
    row = db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if row is None or not row["password_hash"]:
        check_password(body.password, hash_password("timing-equalizer"))   # same work whether or not the email exists
        if row is not None and row["google_sub"]:
            raise HTTPException(401, "This account uses Google. Click Continue with Google.")
        raise HTTPException(401, "Email or password is wrong.")
    if not check_password(body.password, row["password_hash"]):
        raise HTTPException(401, "Email or password is wrong.")
    return {"user": public(row), "token": new_session(row["id"])}


@router.get("/api/auth/me")
def me(authorization: str | None = Header(None)):
    row = user_from_token(authorization)
    if row is None:
        raise HTTPException(401, "Not signed in.")
    return {"user": public(row)}


@router.post("/api/auth/logout")
def logout(authorization: str | None = Header(None)):
    if authorization and authorization.lower().startswith("bearer "):
        with _lock:
            db().execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(authorization.split(None, 1)[1].strip()),))
            db().commit()
    return {"ok": True}


def google_user(sub, email, name, picture):
    """Find or create the account for a verified Google sign-in (links to an existing email account). Returns {user, token}."""
    email = (email or "").strip().lower()
    with _lock:
        row = db().execute("SELECT * FROM users WHERE google_sub = ?", (sub,)).fetchone()
        if row is None and email:
            row = db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if row is not None:
                db().execute("UPDATE users SET google_sub = ?, picture = COALESCE(picture, ?) WHERE id = ?", (sub, picture, row["id"]))
        if row is None:
            uid = secrets.token_hex(8)
            db().execute("INSERT INTO users (id, email, name, google_sub, picture, created) VALUES (?, ?, ?, ?, ?, ?)",
                         (uid, email or f"{sub}@google", (name or email.split("@")[0] or "Google user")[:40], sub, picture, time.time()))
        db().commit()
        row = db().execute("SELECT * FROM users WHERE google_sub = ?", (sub,)).fetchone()
    return {"user": public(row), "token": new_session(row["id"])}


# ---------- phone number + SMS code ----------
TWILIO = {k: os.environ.get(f"TWILIO_{k}", "") for k in ("ACCOUNT_SID", "AUTH_TOKEN", "FROM")}
CODE_MINUTES, RESEND_SECONDS, SENDS_PER_HOUR, MAX_TRIES = 5, 60, 5, 5


class PhoneSend(BaseModel):
    phone: str


class PhoneVerify(BaseModel):
    phone: str
    code: str
    name: str = ""


def normalize_phone(raw):
    """'+855 012 345 678' -> '+85512345678' (drops the national leading 0 after a country code)."""
    raw = raw.strip()
    digits = re.sub(r"\D", "", raw)
    m = re.match(r"^\+(\d{1,3}?)0?(\d{6,12})$", "+" + digits) if raw.startswith("+") else None
    if not raw.startswith("+") or not (8 <= len(digits) <= 15):
        raise HTTPException(400, "Enter your phone number with its country code, e.g. +855 12 345 678.")
    cc_known = next((cc for cc in ("855", "856", "880", "886", "852", "853", "66", "84", "86", "65", "60", "62", "63", "81", "82", "61", "44", "1")
                     if digits.startswith(cc)), None)
    if cc_known:
        rest = digits[len(cc_known):].lstrip("0")
        return f"+{cc_known}{rest}"
    return "+" + (m.group(1) + m.group(2) if m else digits)


def send_sms(phone, text):
    r = requests.post(f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO['ACCOUNT_SID']}/Messages.json",
                      auth=(TWILIO["ACCOUNT_SID"], TWILIO["AUTH_TOKEN"]), data={"From": TWILIO["FROM"], "To": phone, "Body": text}, timeout=15)
    if r.status_code >= 300:
        raise HTTPException(502, "Couldn't send the SMS. Check the number and try again.")


PHONE_LOGIN = os.environ.get("FONGAI_PHONE_LOGIN", "") == "1"   # on hold: Google sign-in only for now


@router.post("/api/auth/phone/send")
def phone_send(body: PhoneSend, request: Request):
    if not PHONE_LOGIN:
        raise HTTPException(503, "Phone sign-in is turned off. Use Continue with Google.")
    phone = normalize_phone(body.phone)
    sms_ready = all(TWILIO.values())
    local = request.client is not None and request.client.host in ("127.0.0.1", "::1", "localhost")
    if not sms_ready and not local:
        raise HTTPException(503, "Phone sign-in isn't available yet. Use Google or email.")
    now = time.time()
    with _lock:
        row = db().execute("SELECT * FROM phone_codes WHERE phone = ?", (phone,)).fetchone()
        sends, hour_start = 1, now
        if row:
            if now - row["sent_at"] < RESEND_SECONDS:
                raise HTTPException(429, f"Please wait {int(RESEND_SECONDS - (now - row['sent_at']))} seconds before asking for a new code.")
            if now - row["hour_start"] < 3600:
                if row["sends_hour"] >= SENDS_PER_HOUR:
                    raise HTTPException(429, "Too many codes for this number. Try again in an hour.")
                sends, hour_start = row["sends_hour"] + 1, row["hour_start"]
        code = f"{secrets.randbelow(10 ** 6):06d}"
        db().execute("INSERT OR REPLACE INTO phone_codes VALUES (?, ?, ?, 0, ?, ?, ?)",
                     (phone, _token_hash(phone + code), now + CODE_MINUTES * 60, now, sends, hour_start))
        db().commit()
    if sms_ready:
        send_sms(phone, f"Your Fong AI code is {code}. It expires in {CODE_MINUTES} minutes.")
        return {"sent": True, "phone": phone}
    print(f"[FongAI test mode] code for {phone}: {code}", flush=True)
    return {"sent": True, "phone": phone, "test_code": code}   # test mode on this computer only


@router.post("/api/auth/phone/verify")
def phone_verify(body: PhoneVerify):
    if not PHONE_LOGIN:
        raise HTTPException(503, "Phone sign-in is turned off. Use Continue with Google.")
    phone = normalize_phone(body.phone)
    code = re.sub(r"\D", "", body.code)
    now = time.time()
    with _lock:
        row = db().execute("SELECT * FROM phone_codes WHERE phone = ?", (phone,)).fetchone()
        if row is None or row["expires"] < now:
            raise HTTPException(400, "This code has expired. Ask for a new one.")
        if row["tries"] >= MAX_TRIES:
            raise HTTPException(429, "Too many wrong codes. Ask for a new one.")
        if not hmac.compare_digest(row["code_hash"], _token_hash(phone + code)):
            db().execute("UPDATE phone_codes SET tries = tries + 1 WHERE phone = ?", (phone,))
            db().commit()
            raise HTTPException(400, "That code is wrong. Check the SMS and try again.")
        db().execute("DELETE FROM phone_codes WHERE phone = ?", (phone,))
        user = db().execute("SELECT * FROM users WHERE phone = ?", (phone,)).fetchone()
        if user is None:
            uid = secrets.token_hex(8)
            name = (body.name.strip() or "Fong user")[:40]
            db().execute("INSERT INTO users (id, name, phone, created) VALUES (?, ?, ?, ?)", (uid, name, phone, now))
            user = db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        db().commit()
    return {"user": public(user), "token": new_session(user["id"])}


# ---------- signing in the terminal (fong login) ----------
# Like GitHub's or Claude's CLI: the terminal shows a short code and opens the browser; the person signs in to their
# FongAI account there and clicks Connect; the terminal, which keeps asking, then receives its own session token.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O, 1/I: easy to read aloud
DEVICE_MINUTES = 10


class DeviceCode(BaseModel):
    device_code: str


class UserCode(BaseModel):
    user_code: str


@router.post("/api/auth/device/start")
def device_start(request: Request):
    device = secrets.token_urlsafe(32)
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    code = f"{code[:4]}-{code[4:]}"
    with _lock:
        db().execute("DELETE FROM device_logins WHERE expires < ?", (time.time(),))
        db().execute("INSERT INTO device_logins (device_hash, user_code, expires) VALUES (?, ?, ?)",
                     (_token_hash(device), code, time.time() + DEVICE_MINUTES * 60))
        db().commit()
    base = str(request.base_url).rstrip("/")
    return {"device_code": device, "user_code": code, "verify_url": f"{base}/cli-login?code={code}",
            "expires_in": DEVICE_MINUTES * 60, "interval": 3}


@router.post("/api/auth/device/approve")
def device_approve(body: UserCode, authorization: str | None = Header(None)):
    """The signed-in person (browser session) connects the terminal that shows this code."""
    user = user_from_token(authorization)
    if user is None:
        raise HTTPException(401, "Sign in first, then click Connect.")
    code = body.user_code.strip().upper()
    with _lock:
        row = db().execute("SELECT * FROM device_logins WHERE user_code = ?", (code,)).fetchone()
        if row is None or row["expires"] < time.time() or row["done"]:
            raise HTTPException(400, "This code has expired. Run fong login again.")
        db().execute("UPDATE device_logins SET user_id = ? WHERE user_code = ?", (user["id"], code))
        db().commit()
    return {"ok": True}


@router.post("/api/auth/device/poll")
def device_poll(body: DeviceCode):
    """The terminal asks every few seconds: {status: pending | expired | ok (+ token, user)}."""
    with _lock:
        row = db().execute("SELECT * FROM device_logins WHERE device_hash = ?", (_token_hash(body.device_code),)).fetchone()
        if row is None or row["done"] or row["expires"] < time.time():
            return {"status": "expired"}
        if not row["user_id"]:
            return {"status": "pending"}
        db().execute("UPDATE device_logins SET done = 1 WHERE device_hash = ?", (row["device_hash"],))
        db().commit()
        user = db().execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
    return {"status": "ok", "token": new_session(user["id"]), "user": public(user)}
