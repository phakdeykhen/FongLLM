"""Voice + document assistant: Whisper (speech->text) -> mxbai (retrieval) -> FongAI, Mistral or Kimi K3.1 Pro (answer).

Run:  cd ~/Documents/FongAI && source .venv/bin/activate && streamlit run assistant/app.py
"""
import io
import json
import os
import sys

import numpy as np
import requests
import soundfile as sf
import streamlit as st
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MODELS = os.path.join(HERE, "models")
DEVICE = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "mistral"
OWN_CKPT = os.path.join(ROOT, "out", "full_sft_768.pth")
QUERY_PROMPT = "Represent this sentence for searching relevant passages: "  # mxbai's recommended query prefix

LLM_MINIMIND = "FongAI (64M, ready-made)"
LLM_OWN = "FongAI (your trained full_sft_768.pth)"
LLM_MISTRAL = "Mistral 7B Instruct (Ollama)"
LLM_KIMI = "Kimi K3.1 Pro (cloud API)"
KIMI_URL = os.environ.get("KIMI_BASE_URL", "https://api.moonshot.ai/v1")
KIMI_MODEL = os.environ.get("KIMI_MODEL", "kimi-k3.1-pro")

st.set_page_config(page_title="FongAI Voice Assistant", page_icon="🎙️", layout="wide")


# ---------- model loaders (cached: each loads once per server run) ----------
@st.cache_resource(show_spinner="Loading Whisper large-v2...")
def load_whisper():
    from transformers import pipeline
    return pipeline("automatic-speech-recognition", model=os.path.join(MODELS, "whisper-large-v2"),
                    torch_dtype=torch.float16, device=DEVICE)


class Embedder:
    """mxbai-embed-large with CLS pooling (per its 1_Pooling/config.json), loaded via plain transformers
    because the repo's pinned sentence-transformers 2.3.1 can't parse mxbai's newer pooling config."""

    def __init__(self, path):
        from transformers import AutoModel, AutoTokenizer
        self.tok = AutoTokenizer.from_pretrained(path)
        self.model = AutoModel.from_pretrained(path).half().eval().to(DEVICE)

    @torch.no_grad()
    def encode(self, texts, normalize_embeddings=True, batch_size=16):
        out = []
        for i in range(0, len(texts), batch_size):
            b = self.tok(texts[i:i + batch_size], padding=True, truncation=True, max_length=512, return_tensors="pt").to(DEVICE)
            e = self.model(**b).last_hidden_state[:, 0].float()
            if normalize_embeddings:
                e = torch.nn.functional.normalize(e, dim=-1)
            out.append(e.cpu().numpy())
        return np.concatenate(out)


@st.cache_resource(show_spinner="Loading mxbai embeddings...")
def load_embedder():
    return Embedder(os.path.join(MODELS, "mxbai-embed-large-v1"))


@st.cache_resource(show_spinner="Loading FongAI...")
def load_minimind(own: bool):
    from transformers import AutoModelForCausalLM, AutoTokenizer
    if own:
        sys.path.insert(0, ROOT)
        from model.model_minimind import MiniMindConfig, MiniMindForCausalLM
        tok = AutoTokenizer.from_pretrained(os.path.join(ROOT, "model"))
        model = MiniMindForCausalLM(MiniMindConfig(hidden_size=768, num_hidden_layers=8))
        model.load_state_dict(torch.load(OWN_CKPT, map_location="cpu"), strict=True)
    else:
        path = os.path.join(MODELS, "fongai-3") if os.path.isdir(os.path.join(MODELS, "fongai-3")) else os.path.join(MODELS, "minimind-3")
        tok = AutoTokenizer.from_pretrained(path)
        # eager attention: torch 2.6's fused SDPA crashes on MPS with grouped-query attention (8 q / 4 kv heads)
        model = AutoModelForCausalLM.from_pretrained(path, attn_implementation="eager")
    return model.half().eval().to(DEVICE), tok


def ollama_ok():
    try:
        tags = requests.get(f"{OLLAMA_URL}/api/tags", timeout=2).json()
        return any(m["name"].split(":")[0] == OLLAMA_MODEL for m in tags.get("models", []))
    except Exception:
        return False


# ---------- pipeline steps ----------
def transcribe(audio_bytes: bytes) -> str:
    data, sr = sf.read(io.BytesIO(audio_bytes), dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    if sr != 16000:
        import librosa
        data = librosa.resample(data, orig_sr=sr, target_sr=16000)
    out = load_whisper()({"raw": data, "sampling_rate": 16000}, chunk_length_s=30,
                         generate_kwargs={"task": "transcribe"})
    return out["text"].strip()


def chunk_text(text: str, size: int = 500, overlap: int = 80):
    text = " ".join(text.split())
    return [text[i:i + size] for i in range(0, max(len(text), 1), size - overlap) if text[i:i + size].strip()]


def index_docs(files):
    chunks, sources = [], []
    for f in files:
        text = f.getvalue().decode("utf-8", errors="ignore")
        for c in chunk_text(text):
            chunks.append(c)
            sources.append(f.name)
    if not chunks:
        return None
    emb = load_embedder().encode(chunks, normalize_embeddings=True, batch_size=16)
    return {"chunks": chunks, "sources": sources, "emb": np.asarray(emb)}


def retrieve(index, query: str, k: int):
    if not index:
        return []
    q = load_embedder().encode([QUERY_PROMPT + query], normalize_embeddings=True)[0]
    scores = index["emb"] @ q
    top = np.argsort(-scores)[:k]
    return [(index["chunks"][i], index["sources"][i], float(scores[i])) for i in top]


def build_messages(question: str, hits, history):
    if hits:
        ctx = "\n\n".join(f"[{i + 1}] {c}" for i, (c, _, _) in enumerate(hits))
        user = f"Answer the question using the context below. If the context does not help, say so.\n\nContext:\n{ctx}\n\nQuestion: {question}"
    else:
        user = question
    return history + [{"role": "user", "content": user}]


def answer_minimind(messages, own: bool, temperature: float, max_new_tokens: int):
    from threading import Thread
    from transformers import TextIteratorStreamer
    model, tok = load_minimind(own)
    prompt = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tok(prompt, return_tensors="pt", truncation=True, max_length=2048).to(DEVICE)
    streamer = TextIteratorStreamer(tok, skip_prompt=True, skip_special_tokens=True)
    Thread(target=model.generate, kwargs=dict(
        input_ids=inputs["input_ids"], attention_mask=inputs["attention_mask"], streamer=streamer,
        max_new_tokens=max_new_tokens, do_sample=True, temperature=temperature, top_p=0.95,
        pad_token_id=tok.pad_token_id, eos_token_id=tok.eos_token_id)).start()
    yield from streamer


def answer_mistral(messages, temperature: float, max_new_tokens: int):
    r = requests.post(f"{OLLAMA_URL}/api/chat", stream=True, timeout=600, json={
        "model": OLLAMA_MODEL, "messages": [{"role": "system", "content": "You are FongAI, a helpful assistant."}] + messages, "stream": True,
        "options": {"temperature": temperature, "num_predict": max_new_tokens}})
    r.raise_for_status()
    for line in r.iter_lines():
        if line:
            part = json.loads(line)
            yield part.get("message", {}).get("content", "")


def answer_kimi(messages, max_new_tokens: int, effort: str):
    """Kimi K3.1 Pro via Moonshot's OpenAI-compatible API. Thinking is always on and
    temperature/top_p are fixed by the API, so they are not sent. Reasoning tokens count
    toward max_completion_tokens, so extra room is added for them."""
    key = os.environ.get("MOONSHOT_API_KEY")
    if not key:
        raise RuntimeError("Set MOONSHOT_API_KEY (get one at https://platform.kimi.ai/console/api-keys)")
    r = requests.post(f"{KIMI_URL}/chat/completions", stream=True, timeout=600,
        headers={"Authorization": f"Bearer {key}"}, json={
        "model": KIMI_MODEL, "stream": True, "reasoning_effort": effort,
        "max_completion_tokens": max_new_tokens + 8192,
        "messages": [{"role": "system", "content": "You are FongAI, a helpful assistant."}] + messages})
    if r.status_code != 200:
        raise RuntimeError(f"Kimi API {r.status_code}: {r.text[:300]}")
    for line in r.iter_lines():
        if not line.startswith(b"data:"):
            continue
        data = line[5:].strip()
        if data == b"[DONE]":
            break
        choices = json.loads(data).get("choices") or [{}]
        text = choices[0].get("delta", {}).get("content")
        if text:
            yield text


# ---------- UI ----------
st.title("🎙️ FongAI Voice + Docs Assistant")
st.caption(f"Whisper large-v2 → mxbai-embed-large → FongAI / Mistral · device: {DEVICE}")

with st.sidebar:
    st.header("Answer model")
    options = [LLM_MINIMIND, LLM_MISTRAL, LLM_KIMI] + ([LLM_OWN] if os.path.exists(OWN_CKPT) else [])
    llm = st.radio("LLM", options, label_visibility="collapsed")
    if llm == LLM_MISTRAL and not ollama_ok():
        st.error("Ollama isn't running or `mistral` isn't pulled. Run: `brew services start ollama && ollama pull mistral`")
    effort = "low"
    if llm == LLM_KIMI:
        if not os.environ.get("MOONSHOT_API_KEY"):
            st.error("Set MOONSHOT_API_KEY before starting Streamlit (key from platform.kimi.ai, needs a $1+ top-up).")
        effort = st.select_slider("Kimi reasoning effort", ["low", "high", "max"], value="low")
        st.caption("Runs on Moonshot's servers (paid per token). Uses no RAM on this Mac.")
    elif llm != LLM_MISTRAL:
        st.caption("FongAI is a tiny model trained mostly on Chinese; expect simple answers.")
    temperature = st.slider("Temperature", 0.0, 1.5, 0.7, 0.05)
    max_new = st.slider("Max answer tokens", 64, 2048, 512, 64)

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

col1, col2 = st.columns(2)
with col1:
    recorded = st.audio_input("🎤 Record a question")
with col2:
    uploaded = st.file_uploader("…or upload audio (wav / flac / mp3 / ogg)", type=["wav", "flac", "mp3", "ogg"])
typed = st.chat_input("…or type a question")

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
    hits = retrieve(st.session_state.get("index"), question, top_k)
    if hits:
        with st.expander(f"Retrieved {len(hits)} passages (mxbai)"):
            for c, src, s in hits:
                st.markdown(f"**{src}** · score {s:.3f}\n\n> {c}")
    messages = build_messages(question, hits, st.session_state.history[-6:])
    with st.chat_message("assistant"):
        try:
            if llm == LLM_KIMI:
                stream = answer_kimi(messages, max_new, effort)
            elif llm == LLM_MISTRAL:
                stream = answer_mistral(messages, temperature, max_new)
            else:
                stream = answer_minimind(messages, llm == LLM_OWN, temperature, max_new)
            reply = st.write_stream(stream)
        except Exception as e:
            reply = f"Error: {e}"
            st.error(reply)
    st.session_state.history += [{"role": "user", "content": question}, {"role": "assistant", "content": reply}]
