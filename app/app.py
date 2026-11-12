"""FongAI combined assistant: text or voice questions -> MiniMind / Mistral answers,
optional document retrieval, and image / video generation as tools.

Run locally:  cd ~/Documents/FongAI && source .venv/bin/activate && streamlit run app/app.py

Every path/URL is an env var so the same file runs on a server later:
  MINIMIND_ASSISTANT_MODELS  folder holding minimind-3 / whisper-large-v2 / mxbai-embed-large-v1
  OLLAMA_URL, OLLAMA_MODEL   Mistral (or any tool-capable Ollama model)
  MINIMIND_IMAGE_MODEL / MINIMIND_VIDEO_MODEL / MINIMIND_MEDIA_DIR  (see scripts/media_tools.py)
"""
import io
import json
import os
import re
import sys

import numpy as np
import requests
import streamlit as st
import torch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from media_tools import MEDIA_DIR, MEDIA_TOOLS, execute_media_tool, needs_translation, translate  # noqa: E402

MODELS = os.environ.get("MINIMIND_ASSISTANT_MODELS", os.path.join(ROOT, "assistant", "models"))
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "mistral")
DEVICE = "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")
QUERY_PROMPT = "Represent this sentence for searching relevant passages: "  # mxbai query prefix
SYSTEM_PROMPT = ("You are FongAI, a helpful assistant. You can create pictures with generate_image and short clips with "
                 "generate_video; call them only when the user asks for an image, picture, drawing, photo or video, "
                 "and write the prompt argument in English. Otherwise just answer.")

LLM_MISTRAL = f"{OLLAMA_MODEL.capitalize()} (Ollama, can call image/video tools)"
LLM_MINIMIND = "FongAI (64M, tiny, mostly Chinese)"

st.set_page_config(page_title="FongAI Assistant", page_icon="✳", layout="centered")


# ---------- model loaders (cached once per server process) ----------
@st.cache_resource(show_spinner="Loading Whisper large-v2...")
def load_whisper():
    from transformers import pipeline
    return pipeline("automatic-speech-recognition", model=os.path.join(MODELS, "whisper-large-v2"),
                    torch_dtype=torch.float16 if DEVICE != "cpu" else torch.float32, device=DEVICE)


@st.cache_resource(show_spinner="Loading mxbai embeddings...")
def load_embedder():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(os.path.join(MODELS, "mxbai-embed-large-v1"), device=DEVICE)


@st.cache_resource(show_spinner="Loading FongAI...")
def load_minimind():
    from transformers import AutoModelForCausalLM, AutoTokenizer
    path = os.path.join(MODELS, "fongai-3") if os.path.isdir(os.path.join(MODELS, "fongai-3")) else os.path.join(MODELS, "minimind-3")
    tok = AutoTokenizer.from_pretrained(path)
    # eager attention: torch 2.6 fused SDPA crashes on MPS with grouped-query attention
    model = AutoModelForCausalLM.from_pretrained(path, attn_implementation="eager")
    return (model.half() if DEVICE != "cpu" else model).eval().to(DEVICE), tok


def ollama_ok():
    try:
        tags = requests.get(f"{OLLAMA_URL}/api/tags", timeout=2).json()
        return any(m["name"].split(":")[0] == OLLAMA_MODEL.split(":")[0] for m in tags.get("models", []))
    except Exception:
        return False


# ---------- voice + documents ----------
def transcribe(audio_bytes):
    import soundfile as sf
    data, sr = sf.read(io.BytesIO(audio_bytes), dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    if sr != 16000:
        import librosa
        data = librosa.resample(data, orig_sr=sr, target_sr=16000)
    out = load_whisper()({"raw": data, "sampling_rate": 16000}, chunk_length_s=30, generate_kwargs={"task": "transcribe"})
    return out["text"].strip()


def index_docs(files):
    chunks, sources = [], []
    for f in files:
        text = " ".join(f.getvalue().decode("utf-8", errors="ignore").split())
        for i in range(0, max(len(text), 1), 420):
            if text[i:i + 500].strip():
                chunks.append(text[i:i + 500])
                sources.append(f.name)
    if not chunks:
        return None
    emb = load_embedder().encode(chunks, normalize_embeddings=True, batch_size=16)
    return {"chunks": chunks, "sources": sources, "emb": np.asarray(emb)}


def retrieve(index, query, k):
    if not index:
        return []
    q = load_embedder().encode([QUERY_PROMPT + query], normalize_embeddings=True)[0]
    top = np.argsort(-(index["emb"] @ q))[:k]
    return [(index["chunks"][i], index["sources"][i], float(index["emb"][i] @ q)) for i in top]


def with_context(question, hits):
    if not hits:
        return question
    ctx = "\n\n".join(f"[{i + 1}] {c}" for i, (c, _, _) in enumerate(hits))
    return f"Answer the question using the context below. If the context does not help, say so.\n\nContext:\n{ctx}\n\nQuestion: {question}"


# ---------- media ----------
def is_khmer(text):
    return any("\u1780" <= c <= "\u17ff" for c in text)


def show_media(items):
    for item in items or []:
        if item.get("type") == "image" and os.path.exists(item["path"]):
            caption = item.get("prompt") + (f" ← {item['original_prompt']}" if item.get("original_prompt") else "")
            st.image(item["path"], caption=caption, width=512)
        elif item.get("type") == "video" and os.path.exists(item["path"]):
            st.video(item["path"])
            st.caption(item.get("prompt"))


def run_tool(name, args, media):
    label = "Generating image" if name == "generate_image" else "Generating video (can take several minutes)"
    with st.spinner(f"{label}: {args.get('prompt', '')}"):
        result = execute_media_tool(name, args)
    if result is None:
        result = {"error": f"unknown tool {name}"}
    if "path" in result:
        media.append(result)
        show_media([result])
    else:
        st.error(result.get("error"))
    return result


# ---------- answer engines (both return reply text; media is appended in place) ----------
def answer_mistral(messages, temperature, max_new, use_tools, media):
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + messages
    reply = ""
    for _ in range(3):  # model -> tool -> model ...
        body = {"model": OLLAMA_MODEL, "messages": msgs, "stream": True,
                "options": {"temperature": temperature, "num_predict": max_new}}
        if use_tools:
            body["tools"] = MEDIA_TOOLS
        r = requests.post(f"{OLLAMA_URL}/api/chat", json=body, stream=True, timeout=600)
        r.raise_for_status()
        tool_calls, text = [], ""

        def chunks():
            nonlocal text
            for line in r.iter_lines():
                if not line:
                    continue
                msg = json.loads(line).get("message", {})
                tool_calls.extend(msg.get("tool_calls") or [])
                piece = msg.get("content", "")
                text += piece
                yield piece

        st.write_stream(chunks())
        reply += text
        if not tool_calls:
            break
        # 16GB machines can't hold Mistral (~4.4GB) and the diffusion model together: unload Mistral first,
        # and don't ask it to comment afterwards (that would reload it and push the image model into swap).
        unload_ollama()
        for tc in tool_calls:
            fn = tc.get("function", {})
            args = fn.get("arguments") or {}
            args = json.loads(args) if isinstance(args, str) else args
            result = run_tool(fn.get("name", ""), args, media)
            done = f"Here is your {result['type']} ({result['seconds']}s)." if "path" in result else f"Sorry, that failed: {result.get('error')}"
            st.markdown(done)
            reply += ("\n\n" if reply else "") + done
        break
    return reply


def unload_ollama():
    try:
        requests.post(f"{OLLAMA_URL}/api/generate", json={"model": OLLAMA_MODEL, "keep_alive": 0}, timeout=30)
    except Exception:
        pass


def answer_minimind(messages, temperature, max_new, use_tools, media):
    from threading import Thread
    from transformers import TextIteratorStreamer
    model, tok = load_minimind()
    msgs, reply = list(messages), ""
    for _ in range(3):
        kw = {"tokenize": False, "add_generation_prompt": True}
        if use_tools:
            kw["tools"] = MEDIA_TOOLS
        prompt = tok.apply_chat_template(msgs, **kw)
        inputs = tok(prompt, return_tensors="pt", truncation=True, max_length=2048).to(DEVICE)
        streamer = TextIteratorStreamer(tok, skip_prompt=True, skip_special_tokens=True)
        Thread(target=model.generate, kwargs=dict(
            input_ids=inputs["input_ids"], attention_mask=inputs["attention_mask"], streamer=streamer,
            max_new_tokens=max_new, do_sample=True, temperature=temperature, top_p=0.9,
            pad_token_id=tok.pad_token_id, eos_token_id=tok.eos_token_id)).start()
        text = st.write_stream(streamer)
        reply += text
        calls = re.findall(r"<tool_call>(.*?)</tool_call>", text, re.DOTALL)
        if not calls:
            break
        msgs.append({"role": "assistant", "content": text})
        for c in calls:
            try:
                tc = json.loads(c.strip())
            except Exception:
                continue
            args = tc.get("arguments") or {}
            args = json.loads(args) if isinstance(args, str) else args
            result = run_tool(tc.get("name", ""), args, media)
            msgs.append({"role": "tool", "content": json.dumps(result, ensure_ascii=False)})
    return reply


# ---------- UI (Claude-style: sidebar nav + chats, centered greeting and composer, user bubbles) ----------
import glob
import html
import time

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,400;8..60,500&display=swap');
:root { --bg:#262624; --panel:#1f1e1d; --raised:#30302e; --bubble:#141413; --border:#3e3e38; --hover:#2c2c29;
        --active:#34342f; --text:#e8e6dc; --muted:#9c9a92; --accent:#d97757; }
#MainMenu, footer, [data-testid="stDecoration"], [data-testid="stAppDeployButton"] { display:none !important; }
.stApp, [data-testid="stAppViewContainer"], header[data-testid="stHeader"] { background: var(--bg) !important; }
.block-container { max-width: 760px; padding-top: 2.5rem; padding-bottom: 8rem; }

/* ---- sidebar: compact full-width rows like Claude ---- */
[data-testid="stSidebar"] { background: var(--panel) !important; border-right: 1px solid #30302c; }
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] { padding: .25rem .75rem 1rem .75rem; }
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 2px; }
[data-testid="stSidebar"] .stButton button { justify-content:flex-start; border:none; background:transparent; color:var(--text);
    padding: 0 .55rem; min-height: 2.05rem; border-radius: 8px; box-shadow:none; }
[data-testid="stSidebar"] .stButton button p { font-size:.9rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; text-align:left; }
[data-testid="stSidebar"] .stButton button span[data-testid="stIconMaterial"] { font-size: 1.15rem; color: var(--text); }
[data-testid="stSidebar"] .stButton button:hover { background: var(--hover); color: var(--text); }
[data-testid="stSidebar"] .stButton button:focus:not(:active) { color: var(--text); border:none; }
.st-key-nav_new button { background: var(--hover) !important; }
.side-brand { font-family:'Source Serif 4', Georgia, serif; font-size:1.55rem; color:var(--text); margin:-2.6rem 0 .9rem .45rem; }
.side-label { color:var(--muted); font-size:.75rem; margin:1.3rem 0 .35rem .55rem; }
.side-foot { color:var(--muted); font-size:.72rem; margin:1.5rem 0 0 .55rem; }

/* ---- greeting ---- */
.hero { text-align:center; margin: 18vh 0 1.6rem 0; font-family:'Source Serif 4', Georgia, serif;
        font-size: 2.45rem; color: var(--text); font-weight:400; letter-spacing:-.01em; }
.hero .spark { color: var(--accent); margin-right:.5rem; }
.page-title { font-family:'Source Serif 4', Georgia, serif; font-size:2rem; margin:.5rem 0 1rem 0; }

/* ---- messages ---- */
.user-row { display:flex; justify-content:flex-end; margin: 1.4rem 0 .6rem 0; }
.user-bubble { background: var(--bubble); color: var(--text); padding:.65rem 1rem; border-radius: 14px;
    max-width: 80%; line-height:1.55; white-space: pre-wrap; word-wrap: break-word; font-size: .97rem; }
[class*="st-key-asst_"] { font-family:'Source Serif 4', Georgia, serif; font-size:1.05rem; line-height:1.7; color:var(--text); }
[class*="st-key-asst_"] code, [class*="st-key-asst_"] pre { font-size:.85rem; }

/* ---- composer: text on top, + bottom-left, send bottom-right (Claude layout) ---- */
[data-testid="stBottom"] > div, [data-testid="stBottomBlockContainer"] { background: var(--bg) !important; }
[data-testid="stChatInput"] { background: var(--raised) !important; border:1px solid var(--border) !important;
    border-radius: 20px !important; box-shadow: 0 4px 24px rgba(0,0,0,.28); }
[data-testid="stChatInput"]:focus-within { border-color: #55554d !important; }
[data-testid="stChatInput"] { height: auto !important; max-height: none !important; }
[data-testid="stChatInput"] > div { position: relative; display: block !important; height: auto !important; box-sizing: content-box; padding: .45rem .9rem 2.9rem 1rem !important; }
[data-testid="stChatInputTextArea"] { font-size: 1rem !important; padding-right: .5rem !important; min-height: 2.6rem !important; }
.st-key-home_input [data-testid="stChatInputTextArea"] { min-height: 3.6rem !important; }
[data-testid="stChatInput"] > div > div:has([data-testid="stChatInputFileUploadButton"]) {
    position: absolute !important; left: .5rem !important; bottom: .45rem !important; top: auto !important; height: auto !important; }
[data-testid="stChatInputFileUploadButton"] { height: auto !important; }
[data-testid="stChatInputFileUploadButton"] + div { display: none; }        /* the divider line */
[data-testid="stChatInputFileUploadButton"] svg { display: none; }           /* paperclip -> + */
[data-testid="stChatInputFileUploadButton"] button::after { content: "+"; font-size: 1.45rem; font-weight: 300;
    color: var(--text); line-height: 1; }
[data-testid="stChatInputFileUploadButton"] button { width: 2rem; height: 2rem; border-radius: 8px; }
[data-testid="stChatInputFileUploadButton"] button:hover { background: var(--hover); }
[data-testid="stChatInput"] > div > div:has(> [data-testid="stChatInputSubmitButton"]) {
    position: absolute !important; right: .6rem !important; bottom: .55rem !important; top: auto !important; height: auto !important; }
[data-testid="stChatInputSubmitButton"] { background: var(--accent) !important; color: #fff !important;
    border-radius: 9px !important; width: 2rem; height: 2rem; }
[data-testid="stChatInputSubmitButton"]:disabled { opacity: .45; }
[data-testid="InputInstructions"] { display: none; }

/* ---- row under the composer: Voice left, model right (muted, borderless) ---- */
.st-key-under_input { margin-top: -.35rem; padding: 0 .4rem; }
.st-key-toolbar { margin-bottom: .5rem; }
.st-key-under_input button, .st-key-toolbar button { background: transparent !important; border: none !important;
    color: var(--text) !important; box-shadow: none !important; padding: .2rem .5rem; min-height: 2rem; }
.st-key-under_input button p, .st-key-toolbar button p { font-size: .9rem; }
.st-key-under_input button:hover, .st-key-toolbar button:hover { background: var(--hover) !important; }
.st-key-under_input [data-baseweb="select"] > div, .st-key-toolbar [data-baseweb="select"] > div {
    background: transparent !important; border: none !important; box-shadow: none !important; font-size: .9rem; }
.st-key-under_input [data-baseweb="select"]:hover > div, .st-key-toolbar [data-baseweb="select"]:hover > div { background: var(--hover) !important; }

/* ---- recent media cards (like Claude's "Recent artifacts") ---- */
.st-key-recent_head { margin-top: 3.2rem; padding: 0 .4rem; }
.recent-title { color: var(--muted); font-size: .92rem; }
.st-key-view_all button { background: transparent !important; border: none !important; padding: 0; min-height: 0; }
.st-key-view_all button p { color: var(--muted); font-size: .92rem; }
.st-key-view_all button:hover p { color: var(--text); }
.mgrid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.mgrid.wide { grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); }
.mcard { background: var(--panel); border: 1px solid #34342f; border-radius: 12px; overflow: hidden; transition: border-color .15s; }
.mcard:hover { border-color: #55554d; }
.mthumb { background: #2a2a27; padding: 14px 14px 0 14px; height: 120px; overflow: hidden; }
.mgrid.wide .mthumb { height: 180px; }
.mthumb img { width: 100%; height: 100%; object-fit: cover; border-radius: 6px 6px 0 0; display: block; }
.mcap { display: flex; justify-content: space-between; gap: 8px; padding: 10px 12px; font-size: .86rem; color: var(--text); }
.mcap span { color: var(--muted); white-space: nowrap; }
@media (max-width: 640px) { .mgrid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .hero { font-size: 1.8rem; } }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

ss = st.session_state
# Widget values survive switching pages (Streamlit drops state of widgets that aren't drawn in a run)
for k in ("llm", "use_tools", "temperature", "max_new", "top_k"):
    if k in ss:
        ss[k] = ss[k]
ss.setdefault("llm", LLM_MISTRAL)
ss.setdefault("use_tools", True)
ss.setdefault("temperature", 0.7)
ss.setdefault("max_new", 512)
ss.setdefault("top_k", 3)
ss.setdefault("chats", {})          # id -> {"title": str, "history": [...]}
ss.setdefault("chat_seq", 0)
ss.setdefault("docs", {})           # name -> UploadedFile
ss.setdefault("view", "home")


def new_chat():
    ss.chat_seq += 1
    cid = f"c{ss.chat_seq}"
    ss.chats[cid] = {"title": "New chat", "history": []}
    ss.current = cid


if "current" not in ss or ss.current not in ss.chats:
    new_chat()
chat = ss.chats[ss.current]


def goto(view, cid=None):
    ss.view = view
    if cid:
        ss.current = cid


def on_prompt():  # callbacks run before the script, so the layout knows a question is coming
    ss.pending = ss.get("prompt")


def on_voice():
    ss.pending_audio = ss.get("voice_rec")


def media_files(kind):
    ext = "png" if kind == "image" else "mp4"
    return sorted(glob.glob(os.path.join(MEDIA_DIR, f"{kind}_*.{ext}")), reverse=True)


def media_date(path):
    try:
        t = time.strptime(os.path.basename(path).split("_")[1] + os.path.basename(path).split("_")[2], "%Y%m%d%H%M%S")
        return time.strftime("%b %d, %H:%M", t)
    except Exception:
        return ""


@st.cache_data(show_spinner=False, max_entries=200)
def thumb(path, mtime, size=480):
    import base64
    from PIL import Image
    im = Image.open(path).convert("RGB")
    im.thumbnail((size, size))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=82)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def image_cards(files, wide=False):
    cards = "".join(
        f'<div class="mcard"><div class="mthumb"><img src="{thumb(f, os.path.getmtime(f), 640 if wide else 400)}" alt="Generated image"></div>'
        f'<div class="mcap">Image<span>{media_date(f)}</span></div></div>' for f in files)
    st.markdown(f'<div class="mgrid{" wide" if wide else ""}">{cards}</div>', unsafe_allow_html=True)


# ---- sidebar ----
NAV = [("new", "New chat", ":material/add:"), ("search", "Search", ":material/search:"),
       ("home", "Home", ":material/home:"), ("images", "Images", ":material/image:"),
       ("videos", "Videos", ":material/movie:"), ("docs", "Documents", ":material/folder:"),
       ("settings", "Settings", ":material/tune:")]
with st.sidebar:
    st.markdown('<div class="side-brand">FongAI</div>', unsafe_allow_html=True)
    for name, label, icon in NAV:
        if st.button(label, icon=icon, key=f"nav_{name}", width="stretch"):
            if name == "new":
                if chat["history"]:
                    new_chat()
                name = "home"
            goto(name)
            st.rerun()
    recent = [cid for cid in reversed(list(ss.chats)) if ss.chats[cid]["history"]]
    if recent:
        st.markdown('<div class="side-label">Recents</div>', unsafe_allow_html=True)
    for cid in recent:
        st.button(ss.chats[cid]["title"], key=f"chat_{cid}", on_click=goto, args=("home", cid), width="stretch")
    st.markdown(f'<div class="side-foot">device: {DEVICE}</div>', unsafe_allow_html=True)

# highlight the current page and chat
active = [] if ss.view == "home" and chat["history"] else [f".st-key-nav_{ss.view} button"] + ([f".st-key-chat_{ss.current} button"] if ss.view == "home" else [])
st.markdown(f"<style>{', '.join(active)} {{ background: var(--active) !important; }}</style>", unsafe_allow_html=True)


def model_picker():
    st.selectbox("Model", [LLM_MISTRAL, LLM_MINIMIND], key="llm", label_visibility="collapsed", width=230,
                 format_func=lambda m: f"{OLLAMA_MODEL.capitalize()} · Ollama" if m == LLM_MISTRAL else "FongAI · 64M",
                 help="Mistral runs in Ollama and can create images/videos. FongAI is the tiny 64M model trained here.")


def voice_button():
    with st.popover("Voice", icon=":material/mic:"):
        st.audio_input("Record a question", key="voice_rec", on_change=on_voice, label_visibility="collapsed")


def composer():
    st.chat_input("How can I help you today?", key="prompt", on_submit=on_prompt, accept_file="multiple",
                  file_type=["txt", "md", "wav", "flac", "mp3", "ogg", "m4a"])


def user_bubble(text):
    st.markdown(f'<div class="user-row"><div class="user-bubble">{html.escape(text)}</div></div>',
                unsafe_allow_html=True)


def ollama_warning():
    if ss.llm == LLM_MISTRAL and not ollama_ok():
        st.warning(f"Ollama isn't running or `{OLLAMA_MODEL}` isn't pulled. Run: "
                   f"`brew services start ollama && ollama pull {OLLAMA_MODEL}`", icon=":material/warning:")


# ---------- pages ----------
def page_search():
    st.markdown('<div class="page-title">Search</div>', unsafe_allow_html=True)
    q = st.text_input("Search your chats", placeholder="Search your chats…", label_visibility="collapsed").strip().lower()
    found = [(cid, c) for cid, c in reversed(list(ss.chats.items())) if c["history"] and
             (not q or q in c["title"].lower() or any(q in m["content"].lower() for m in c["history"]))]
    if not found:
        st.caption("No chats match." if q else "No chats yet.")
    for cid, c in found:
        st.button(f"{c['title']}  ·  {len(c['history']) // 2} messages", key=f"found_{cid}", on_click=goto,
                  args=("home", cid), width="stretch")


def page_media(kind):
    files = media_files(kind)
    st.markdown(f'<div class="page-title">{"Images" if kind == "image" else "Videos"}</div>', unsafe_allow_html=True)
    st.caption(f"{len(files)} {kind}s in `{os.path.relpath(MEDIA_DIR, ROOT)}`. Create more in a chat with `/{kind} <prompt>`.")
    if kind == "image":
        image_cards(files, wide=True)
        return
    cols = st.columns(2)
    for i, f in enumerate(files):
        with cols[i % len(cols)]:
            with st.container(key=f"card_{kind}_{i}"):
                if kind == "image":
                    st.image(f, width="stretch")
                else:
                    st.video(f)
                st.markdown(f'<div class="card-cap">{kind.title()}<span>{media_date(f)}</span></div>', unsafe_allow_html=True)


def page_docs():
    st.markdown('<div class="page-title">Documents</div>', unsafe_allow_html=True)
    st.caption("Answers use these files as context. You can also attach them with the + in the message box.")
    up = st.file_uploader("Add text / Markdown files", type=["txt", "md"], accept_multiple_files=True)
    for f in up or []:
        ss.docs[f.name] = f
    st.slider("Passages to retrieve per question", 1, 8, key="top_k")
    for name in list(ss.docs):
        c1, c2 = st.columns([6, 1])
        c1.markdown(f":material/description: {name}")
        if c2.button("Remove", key=f"rm_{name}"):
            del ss.docs[name]
            st.rerun()
    idx = ss.get("index")
    st.caption(f"{len(idx['chunks'])} passages indexed" if idx else "No documents: plain chat mode")


def page_settings():
    st.markdown('<div class="page-title">Settings</div>', unsafe_allow_html=True)
    model_picker()
    ollama_warning()
    st.checkbox("Let the model generate images/videos", key="use_tools",
                help="The model decides when to call the tools. You can always use /image or /video directly.")
    st.slider("Temperature", 0.0, 1.5, step=0.05, key="temperature")
    st.slider("Max answer tokens", 64, 2048, step=64, key="max_new")
    st.caption("Direct commands: `/image <prompt>` (~5 s) · `/video <prompt>` (minutes). "
               "Khmer and other languages are translated to English automatically (Hy-MT2).")
    if chat["history"] and st.button("Delete current chat", icon=":material/delete:"):
        del ss.chats[ss.current]
        ss.pop("current")
        st.rerun()


def answer(question, history):
    media, llm = [], ss.llm
    with st.container(key=f"asst_{len(history) + 1}"):
        try:
            cmd, _, prompt = question.strip().partition(" ")
            if cmd in ("/image", "/video") and prompt.strip():
                unload_ollama()
                result = run_tool("generate_image" if cmd == "/image" else "generate_video", {"prompt": prompt.strip()}, media)
                reply = f"`{cmd}` {prompt.strip()}" + (f" ({result['seconds']}s)" if "seconds" in result else "")
                st.markdown(reply)
            else:
                hits = retrieve(ss.get("index"), question, ss.top_k)
                if hits:
                    with st.expander(f"Retrieved {len(hits)} passages"):
                        for c, src, s in hits:
                            st.markdown(f"**{src}** · score {s:.3f}\n\n> {c}")
                khmer = is_khmer(question) and llm == LLM_MISTRAL
                asked = question
                if khmer:  # Mistral understands Khmer poorly: translate in, answer in English, translate back
                    with st.spinner("Translating from Khmer..."):
                        asked = translate(question, "English")
                    st.caption(f"🇰🇭 → 🇬🇧 {asked}")
                past = [{"role": m["role"], "content": m["content"]} for m in history[-6:]]
                messages = past + [{"role": "user", "content": with_context(asked, hits)}]
                engine = answer_mistral if llm == LLM_MISTRAL else answer_minimind
                reply = engine(messages, ss.temperature, ss.max_new, ss.use_tools, media)
                if khmer and reply.strip() and not media:
                    with st.spinner("Translating to Khmer..."):
                        reply_km = translate(reply, "Khmer")
                    st.markdown(f"🇰🇭 {reply_km}")
                    reply = f"{reply_km}\n\n<sub>English: {reply}</sub>"
        except Exception as e:
            reply = f"Error: {e}"
            st.error(reply)
    return reply, media


def page_home():
    # collect what was sent (text, attached files, or a voice recording)
    typed, audio = ss.pop("pending", None), ss.pop("pending_audio", None)
    question = None
    if typed:
        text = typed if isinstance(typed, str) else typed.text
        question = (text or "").strip() or None
        for f in ([] if isinstance(typed, str) else typed.files or []):
            if f.name.lower().endswith((".txt", ".md")):
                ss.docs[f.name] = f
            else:
                audio = f
    refresh_index()
    if not question and audio:
        with st.spinner("Transcribing with Whisper..."):
            question = transcribe(audio.getvalue())

    history = chat["history"]
    if not history and not question:  # Home: greeting, composer, model row, recent images
        st.markdown('<div class="hero"><span class="spark">✳</span>Coffee and FongAI time?</div>', unsafe_allow_html=True)
        with st.container(key="home_input"):
            composer()
        with st.container(key="under_input", horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
            voice_button()
            model_picker()
        ollama_warning()
        if ss.docs:
            st.caption(f":material/attach_file: {len(ss.docs)} document(s) attached: " + ", ".join(ss.docs))
        images = media_files("image")[:3]
        if images:
            with st.container(key="recent_head", horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
                st.markdown('<span class="recent-title">Recent images</span>', unsafe_allow_html=True, width="content")
                st.button("View all", key="view_all", on_click=goto, args=("images",))
            image_cards(images)
        return

    with st.container(key="toolbar", horizontal=True, horizontal_alignment="right"):
        voice_button()
        model_picker()
    for i, m in enumerate(history):
        if m["role"] == "user":
            user_bubble(m["content"])
        else:
            with st.container(key=f"asst_{i}"):
                st.markdown(m["content"], unsafe_allow_html=True)
                show_media(m.get("media"))
    composer()
    if question:
        if not history:
            chat["title"] = question[:40] + ("…" if len(question) > 40 else "")
        user_bubble(question)
        reply, media = answer(question, history)
        history += [{"role": "user", "content": question}, {"role": "assistant", "content": reply, "media": media}]
        if len(history) == 2:
            st.rerun()  # show the new chat under Recents


def refresh_index():
    key = tuple(sorted((n, f.size) for n, f in ss.docs.items()))
    if key != ss.get("doc_key"):
        ss.doc_key = key
        ss.index = index_docs(list(ss.docs.values())) if ss.docs else None


refresh_index()
{"home": page_home, "search": page_search, "images": lambda: page_media("image"), "videos": lambda: page_media("video"),
 "docs": page_docs, "settings": page_settings}[ss.view]()
