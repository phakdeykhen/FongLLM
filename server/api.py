"""FongAI backend for the React frontend (web/).

Run:  cd ~/Documents/FongAI && source .venv/bin/activate && uvicorn server.api:app --port 8000
Then: cd web && npm run dev        (development, http://localhost:5173)
  or: cd web && npm run build      (then http://localhost:8000 serves the built UI)

Same env vars as app/app.py: MINIMIND_ASSISTANT_MODELS, OLLAMA_URL, OLLAMA_MODEL, MINIMIND_MEDIA_DIR, ...

/api/chat streams NDJSON events, one JSON object per line:
  {"type": "text", "delta": "..."}          answer text as it is generated
  {"type": "status", "text": "..."}         progress (translating, generating an image, ...); "" clears it
  {"type": "sources", "items": [...]}       retrieved document passages
  {"type": "media", "item": {...}}          a generated image or video (url under /media/)
  {"type": "error", "text": "..."}
  {"type": "done"}
"""
import io
import json
import os
import re
import sys
import time
from functools import lru_cache
from threading import Lock, Thread

import numpy as np
import requests
import torch
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from media_tools import MEDIA_DIR, MEDIA_TOOLS, execute_media_tool, translate  # noqa: E402

MODELS = os.environ.get("MINIMIND_ASSISTANT_MODELS", os.path.join(ROOT, "assistant", "models"))
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "mistral")
FONG_MODEL = os.environ.get("FONG_MODEL", "fongai")   # our own fine-tune, built by finetune/run.sh
OLLAMA_IDS = {"mistral": OLLAMA_MODEL, "fong4": FONG_MODEL}   # app model id -> Ollama model name
# Optional "Continue with Google": create an OAuth client ID (type "Web application") at
# https://console.cloud.google.com/apis/credentials with authorized JavaScript origin http://localhost:8000
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
DEVICE = "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")
QUERY_PROMPT = "Represent this sentence for searching relevant passages: "  # mxbai query prefix
SYSTEM_PROMPT = ("You are {name}, a helpful assistant made by Fong. If asked who you are or which model you are, "
                 "say you are {name}; never call yourself Mistral or Qwen or mention Ollama. You can create pictures with generate_image and short clips with "
                 "generate_video; call them only when the user asks for an image, picture, drawing, photo or video, "
                 "and write the prompt argument in English. Otherwise just answer.")
MODEL_INFO = [
    {"id": "fong4", "name": "FongAI 4", "detail": "Our own model · fine-tuned from Qwen 2.5 7B"},
    {"id": "mistral", "name": "FongAI 3.4", "detail": "Smart and fast · creates images and videos"},
    {"id": "fongai", "name": "FongAI 3.2", "detail": "Tiny 64M model trained here · mostly Chinese"},
]

app = FastAPI(title="FongAI")
GPU_LOCK = Lock()  # one generation at a time: the models share one GPU / unified memory


# ---------- model loaders (once per process) ----------
@lru_cache(maxsize=1)
def load_whisper():
    from transformers import pipeline
    return pipeline("automatic-speech-recognition", model=os.path.join(MODELS, "whisper-large-v2"),
                    torch_dtype=torch.float16 if DEVICE != "cpu" else torch.float32, device=DEVICE)


@lru_cache(maxsize=1)
def load_embedder():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(os.path.join(MODELS, "mxbai-embed-large-v1"), device=DEVICE)


@lru_cache(maxsize=1)
def load_minimind():
    from transformers import AutoModelForCausalLM, AutoTokenizer
    path = os.path.join(MODELS, "fongai-3")
    if not os.path.isdir(path):
        path = os.path.join(MODELS, "minimind-3")
    tok = AutoTokenizer.from_pretrained(path)
    # eager attention: torch 2.6 fused SDPA crashes on MPS with grouped-query attention
    model = AutoModelForCausalLM.from_pretrained(path, attn_implementation="eager")
    return (model.half() if DEVICE != "cpu" else model).eval().to(DEVICE), tok


def ollama_ok(name=OLLAMA_MODEL):
    try:
        tags = requests.get(f"{OLLAMA_URL}/api/tags", timeout=2).json()
        return any(m["name"].split(":")[0] == name.split(":")[0] for m in tags.get("models", []))
    except Exception:
        return False


def unload_ollama():
    for name in set(OLLAMA_IDS.values()):
        try:
            requests.post(f"{OLLAMA_URL}/api/generate", json={"model": name, "keep_alive": 0}, timeout=30)
        except Exception:
            pass


# ---------- documents (kept in memory; this is a single-user local app) ----------
DOCS = {}   # name -> text
INDEX = {"chunks": [], "sources": [], "emb": None}


def rebuild_index():
    chunks, sources = [], []
    for name, raw in DOCS.items():
        text = " ".join(raw.split())
        for i in range(0, max(len(text), 1), 420):
            if text[i:i + 500].strip():
                chunks.append(text[i:i + 500])
                sources.append(name)
    emb = np.asarray(load_embedder().encode(chunks, normalize_embeddings=True, batch_size=16)) if chunks else None
    INDEX.update(chunks=chunks, sources=sources, emb=emb)


def retrieve(query, k):
    if INDEX["emb"] is None or k <= 0:
        return []
    q = load_embedder().encode([QUERY_PROMPT + query], normalize_embeddings=True)[0]
    scores = INDEX["emb"] @ q
    return [{"text": INDEX["chunks"][i], "source": INDEX["sources"][i], "score": round(float(scores[i]), 3)}
            for i in np.argsort(-scores)[:k]]


def with_context(question, hits):
    if not hits:
        return question
    ctx = "\n\n".join(f"[{i + 1}] {h['text']}" for i, h in enumerate(hits))
    return f"Answer the question using the context below. If the context does not help, say so.\n\nContext:\n{ctx}\n\nQuestion: {question}"


# ---------- media ----------
def media_item(path, kind=None, prompt=None):
    name = os.path.basename(path)
    kind = kind or name.split("_")[0]
    try:
        date = time.strftime("%Y-%m-%dT%H:%M:%S", time.strptime("".join(name.split("_")[1:3]), "%Y%m%d%H%M%S"))
    except Exception:
        date = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(path)))
    return {"type": kind, "name": name, "url": f"/media/{name}", "date": date, "prompt": prompt}


def run_tool(name, args):
    """Generator: status events, then a media or error event. Returns the tool result dict."""
    label = "Generating image" if name == "generate_image" else "Generating video (can take several minutes)"
    yield {"type": "status", "text": f"{label}: {args.get('prompt', '')}"}
    result = execute_media_tool(name, args) or {"error": f"unknown tool {name}"}
    yield {"type": "status", "text": ""}
    if "path" in result:
        item = media_item(result["path"], result.get("type"), result.get("prompt"))
        item["seconds"] = result.get("seconds")
        yield {"type": "media", "item": item}
    else:
        yield {"type": "error", "text": result.get("error", "generation failed")}
    return result


# ---------- answer engines (generators of events) ----------
def answer_ollama(messages, temperature, max_new, use_tools, name=OLLAMA_MODEL):
    label = next((m["name"] for m in MODEL_INFO if OLLAMA_IDS.get(m["id"]) == name), "Fong AI")
    msgs = [{"role": "system", "content": SYSTEM_PROMPT.format(name=label)}] + messages
    body = {"model": name, "messages": msgs, "stream": True,
            "options": {"temperature": temperature, "num_predict": max_new}}
    if use_tools:
        body["tools"] = MEDIA_TOOLS
    r = requests.post(f"{OLLAMA_URL}/api/chat", json=body, stream=True, timeout=600)
    r.raise_for_status()
    tool_calls, text = [], ""
    for line in r.iter_lines():
        if not line:
            continue
        msg = json.loads(line).get("message", {})
        tool_calls.extend(msg.get("tool_calls") or [])
        piece = msg.get("content", "")
        if piece:
            text += piece
            yield {"type": "text", "delta": piece}
    if tool_calls:
        # 16GB machines can't hold Mistral (~4.4GB) and the diffusion model together: unload Mistral first,
        # and don't ask it to comment afterwards (that would reload it and push the image model into swap).
        unload_ollama()
        for tc in tool_calls:
            fn = tc.get("function", {})
            args = fn.get("arguments") or {}
            args = json.loads(args) if isinstance(args, str) else args
            result = yield from run_tool(fn.get("name", ""), args)
            done = f"Here is your {result['type']} ({result['seconds']}s)." if "path" in result else ""
            if done:
                yield {"type": "text", "delta": ("\n\n" if text else "") + done}


def answer_minimind(messages, temperature, max_new, use_tools):
    from transformers import TextIteratorStreamer
    model, tok = load_minimind()
    msgs = list(messages)
    for _ in range(3):
        kw = {"tokenize": False, "add_generation_prompt": True}
        if use_tools:
            kw["tools"] = MEDIA_TOOLS
        prompt = tok.apply_chat_template(msgs, **kw)
        inputs = tok(prompt, return_tensors="pt", truncation=True, max_length=2048).to(DEVICE)
        streamer = TextIteratorStreamer(tok, skip_prompt=True, skip_special_tokens=True)
        Thread(target=model.generate, kwargs=dict(
            input_ids=inputs["input_ids"], attention_mask=inputs["attention_mask"], streamer=streamer,
            max_new_tokens=max_new, do_sample=True, temperature=max(temperature, 0.01), top_p=0.9,
            pad_token_id=tok.pad_token_id, eos_token_id=tok.eos_token_id)).start()
        text = ""
        for piece in streamer:
            text += piece
            yield {"type": "text", "delta": piece}
        calls = re.findall(r"<tool_call>(.*?)</tool_call>", text, re.DOTALL)
        if not calls:
            return
        msgs.append({"role": "assistant", "content": text})
        for c in calls:
            try:
                tc = json.loads(c.strip())
            except Exception:
                continue
            args = tc.get("arguments") or {}
            args = json.loads(args) if isinstance(args, str) else args
            result = yield from run_tool(tc.get("name", ""), args)
            msgs.append({"role": "tool", "content": json.dumps(result, ensure_ascii=False)})


def is_khmer(text):
    return any("ក" <= c <= "៿" for c in text)


class ChatRequest(BaseModel):
    messages: list[dict]            # [{"role": "user"|"assistant", "content": str}, ...]; last one is the question
    model: str = "mistral"
    temperature: float = 0.7
    max_new: int = 512
    use_tools: bool = True
    top_k: int = 3


def chat_events(req: ChatRequest):
    question = req.messages[-1]["content"].strip()
    history = [{"role": m["role"], "content": m["content"]} for m in req.messages[:-1]][-6:]
    cmd, _, prompt = question.partition(" ")
    if cmd in ("/image", "/video") and prompt.strip():
        unload_ollama()
        result = yield from run_tool("generate_image" if cmd == "/image" else "generate_video", {"prompt": prompt.strip()})
        if "seconds" in result:
            yield {"type": "text", "delta": f"Here is your {result['type']} ({result['seconds']}s)."}
        return

    if INDEX["emb"] is not None:
        yield {"type": "status", "text": "Searching your documents..."}
        hits = retrieve(question, req.top_k)
        yield {"type": "sources", "items": hits}
    else:
        hits = []

    ollama_name = OLLAMA_IDS.get(req.model)
    mistral = ollama_name is not None   # any Ollama-served model (FongAI 4 or 3.4)
    if mistral and not ollama_ok(ollama_name):
        fix = "zsh finetune/run.sh" if req.model == "fong4" else f"ollama pull {ollama_name}"
        yield {"type": "error", "text": "This model isn't available right now. Pick another model, or start it: "
                                        f"brew services start ollama && {fix}"}
        return
    khmer = is_khmer(question) and mistral
    asked = question
    if khmer:  # Mistral understands Khmer poorly: translate in, answer in English, translate back
        yield {"type": "status", "text": "Translating from Khmer..."}
        asked = translate(question, "English")
    yield {"type": "status", "text": "Thinking..." if mistral else "Loading FongAI 3.2..."}
    engine = (lambda *a: answer_ollama(*a, name=ollama_name)) if mistral else answer_minimind
    reply, first = "", True
    for ev in engine(history + [{"role": "user", "content": with_context(asked, hits)}],
                     req.temperature, req.max_new, req.use_tools):
        if first and ev["type"] == "text":
            yield {"type": "status", "text": ""}
            first = False
        if ev["type"] == "text":
            reply += ev["delta"]
        yield ev
    if khmer and reply.strip():
        yield {"type": "status", "text": "Translating to Khmer..."}
        yield {"type": "text", "delta": "\n\n---\n\n🇰🇭 " + translate(reply, "Khmer")}


# ---------- routes ----------
@app.get("/api/info")
def info():
    return {"device": DEVICE, "models": [m for m in MODEL_INFO if m["id"] != "fong4" or ollama_ok(FONG_MODEL)],
            "ollama": ollama_ok(), "ollama_model": OLLAMA_MODEL,
            "google_client_id": GOOGLE_CLIENT_ID or None}


class GoogleLogin(BaseModel):
    credential: str   # the ID token Google Identity Services gives the browser


@app.post("/api/auth/google")
def auth_google(body: GoogleLogin):
    """Checks a Google sign-in and returns the profile. Nothing is stored on the server."""
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(400, "Google sign-in isn't set up. Start the server with GOOGLE_CLIENT_ID=<your client id>.")
    try:  # Google checks the signature and expiry for us
        r = requests.get("https://oauth2.googleapis.com/tokeninfo", params={"id_token": body.credential}, timeout=10)
    except requests.RequestException:
        raise HTTPException(502, "Couldn't reach Google to check the sign-in. Check your internet connection.")
    t = r.json() if r.ok else {}
    if not r.ok or t.get("aud") != GOOGLE_CLIENT_ID or t.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise HTTPException(401, "Google sign-in failed. Please try again.")
    return {"name": t.get("name") or t.get("email", "").split("@")[0], "email": t.get("email"),
            "picture": t.get("picture"), "provider": "google"}


class ImageRequest(BaseModel):
    prompt: str


@app.post("/api/image")
def make_image(body: ImageRequest):
    """Generates one image directly (Images page). Same model and folder as /image in chat."""
    if not body.prompt.strip():
        raise HTTPException(400, "Describe the image you want.")
    with GPU_LOCK:
        unload_ollama()
        result = execute_media_tool("generate_image", {"prompt": body.prompt.strip()})
    if not result or "path" not in result:
        raise HTTPException(500, (result or {}).get("error", "Image generation failed."))
    item = media_item(result["path"], "image", result.get("prompt"))
    item["seconds"] = result.get("seconds")
    return item


@app.post("/api/chat")
def chat(req: ChatRequest):
    if not req.messages or req.messages[-1].get("role") != "user":
        raise HTTPException(400, "the last message must be from the user")

    def stream():
        with GPU_LOCK:
            try:
                for ev in chat_events(req):
                    yield json.dumps(ev, ensure_ascii=False) + "\n"
            except Exception as e:
                yield json.dumps({"type": "error", "text": f"{type(e).__name__}: {e}"}) + "\n"
            yield json.dumps({"type": "status", "text": ""}) + "\n"
            yield json.dumps({"type": "done"}) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...)):
    import soundfile as sf
    raw = await file.read()
    try:
        data, sr = sf.read(io.BytesIO(raw), dtype="float32")
    except Exception:
        raise HTTPException(400, "Couldn't read that audio. Use WAV, FLAC, OGG or MP3.")
    if data.ndim > 1:
        data = data.mean(axis=1)
    if sr != 16000:
        import librosa
        data = librosa.resample(data, orig_sr=sr, target_sr=16000)
    with GPU_LOCK:
        out = load_whisper()({"raw": data, "sampling_rate": 16000}, chunk_length_s=30, generate_kwargs={"task": "transcribe"})
    return {"text": out["text"].strip()}


@app.get("/api/documents")
def list_documents():
    return {"documents": [{"name": n, "chars": len(t)} for n, t in DOCS.items()], "passages": len(INDEX["chunks"])}


@app.post("/api/documents")
async def add_documents(files: list[UploadFile] = File(...)):
    for f in files:
        if not f.filename.lower().endswith((".txt", ".md")):
            raise HTTPException(400, f"{f.filename}: only .txt and .md files are supported")
        DOCS[f.filename] = (await f.read()).decode("utf-8", errors="ignore")
    with GPU_LOCK:
        rebuild_index()
    return list_documents()


@app.delete("/api/documents/{name}")
def delete_document(name: str):
    DOCS.pop(name, None)
    with GPU_LOCK:
        rebuild_index()
    return list_documents()


@app.get("/api/media")
def list_media(kind: str | None = None):
    os.makedirs(MEDIA_DIR, exist_ok=True)
    items = [media_item(os.path.join(MEDIA_DIR, n)) for n in os.listdir(MEDIA_DIR)
             if n.startswith(("image_", "video_")) and n.endswith((".png", ".mp4"))]
    if kind:
        items = [i for i in items if i["type"] == kind]
    return {"items": sorted(items, key=lambda i: i["name"], reverse=True)}


os.makedirs(MEDIA_DIR, exist_ok=True)
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")

DIST = os.path.join(ROOT, "web", "dist")
if os.path.isdir(DIST):  # serve the built React app (npm run build) from the same port
    app.mount("/assets", StaticFiles(directory=os.path.join(DIST, "assets")), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        file = os.path.join(DIST, path)
        return FileResponse(file if path and os.path.isfile(file) else os.path.join(DIST, "index.html"))
