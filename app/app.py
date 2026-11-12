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
from media_tools import MEDIA_TOOLS, execute_media_tool, needs_translation, translate  # noqa: E402

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

st.set_page_config(page_title="FongAI Assistant", page_icon="🤖", layout="wide")


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


# ---------- UI ----------
st.title("🤖 FongAI Assistant")
st.caption(f"Type or speak · answers by Mistral or FongAI · /image and /video generation · device: {DEVICE}")

with st.sidebar:
    st.header("Answer model")
    llm = st.radio("LLM", [LLM_MISTRAL, LLM_MINIMIND], label_visibility="collapsed")
    if llm == LLM_MISTRAL and not ollama_ok():
        st.error(f"Ollama isn't running or `{OLLAMA_MODEL}` isn't pulled. Run: `brew services start ollama && ollama pull {OLLAMA_MODEL}`")
    use_tools = st.checkbox("Let the model generate images/videos", value=True,
                            help="The model decides when to call the tools. You can always use /image or /video directly.")
    temperature = st.slider("Temperature", 0.0, 1.5, 0.7, 0.05)
    max_new = st.slider("Max answer tokens", 64, 2048, 512, 64)
    st.caption("Direct commands: `/image <prompt>` (~5 s) · `/video <prompt>` (minutes). "
               "Khmer and other languages are translated to English automatically (Hy-MT2).")

    st.header("Documents (optional)")
    files = st.file_uploader("Text / Markdown files", type=["txt", "md"], accept_multiple_files=True)
    top_k = st.slider("Passages to retrieve", 1, 8, 3)
    key = tuple((f.name, f.size) for f in files or [])
    if key != st.session_state.get("doc_key"):
        st.session_state.doc_key = key
        st.session_state.index = index_docs(files) if files else None
    idx = st.session_state.get("index")
    st.caption(f"{len(idx['chunks'])} passages indexed" if idx else "No documents: plain chat mode")
    if st.button("Clear chat"):
        st.session_state.history = []

st.session_state.setdefault("history", [])
for m in st.session_state.history:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        show_media(m.get("media"))

col1, col2 = st.columns(2)
with col1:
    recorded = st.audio_input("🎤 Record a question")
with col2:
    uploaded = st.file_uploader("…or upload audio (wav / flac / mp3 / ogg)", type=["wav", "flac", "mp3", "ogg"])
typed = st.chat_input("Type a message, or /image … / /video …")

question = None
audio = recorded or uploaded
audio_key = (audio.name, audio.size) if audio else None
if typed:
    question = typed
elif audio and audio_key != st.session_state.get("last_audio"):
    st.session_state.last_audio = audio_key
    with st.spinner("Transcribing with Whisper..."):
        question = transcribe(audio.getvalue())

if question:
    with st.chat_message("user"):
        st.markdown(question)
    media = []
    with st.chat_message("assistant"):
        try:
            cmd, _, prompt = question.strip().partition(" ")
            if cmd in ("/image", "/video") and prompt.strip():
                unload_ollama()
                result = run_tool("generate_image" if cmd == "/image" else "generate_video", {"prompt": prompt.strip()}, media)
                reply = f"`{cmd}` {prompt.strip()}" + (f" ({result['seconds']}s)" if "seconds" in result else "")
                st.markdown(reply)
            else:
                hits = retrieve(st.session_state.get("index"), question, top_k)
                if hits:
                    with st.expander(f"Retrieved {len(hits)} passages (mxbai)"):
                        for c, src, s in hits:
                            st.markdown(f"**{src}** · score {s:.3f}\n\n> {c}")
                khmer = is_khmer(question) and llm == LLM_MISTRAL
                asked = question
                if khmer:  # Mistral understands Khmer poorly: translate in, answer in English, translate back
                    with st.spinner("Translating from Khmer..."):
                        asked = translate(question, "English")
                    st.caption(f"🇰🇭 → 🇬🇧 {asked}")
                history = [{"role": m["role"], "content": m["content"]} for m in st.session_state.history[-6:]]
                messages = history + [{"role": "user", "content": with_context(asked, hits)}]
                engine = answer_mistral if llm == LLM_MISTRAL else answer_minimind
                reply = engine(messages, temperature, max_new, use_tools, media)
                if khmer and reply.strip() and not media:
                    with st.spinner("Translating to Khmer..."):
                        reply_km = translate(reply, "Khmer")
                    st.markdown(f"🇰🇭 {reply_km}")
                    reply = f"{reply_km}\n\n<sub>English: {reply}</sub>"
        except Exception as e:
            reply = f"Error: {e}"
            st.error(reply)
    st.session_state.history += [{"role": "user", "content": question},
                                 {"role": "assistant", "content": reply, "media": media}]
