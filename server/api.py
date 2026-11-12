"""FongAI backend for the React frontend (web/).

Run:  cd ~/Documents/FongAI && source .venv/bin/activate && uvicorn server.api:app --port 8000
Then: cd web && npm run dev        (development, http://localhost:5173)
  or: cd web && npm run build      (then http://localhost:8000 serves the built UI)

Same env vars as app/app.py: MINIMIND_ASSISTANT_MODELS, OLLAMA_URL, OLLAMA_MODEL, MINIMIND_MEDIA_DIR, ...

/api/chat streams NDJSON events, one JSON object per line:
  {"type": "text", "delta": "..."}          answer text as it is generated
  {"type": "status", "text": "..."}         progress (translating, generating an image, ...); "" clears it
  {"type": "progress", "kind": "image", "value": 42}   image/video generation, percent done (until the media event)
  {"type": "sources", "items": [...]}       retrieved document passages
  {"type": "media", "item": {...}}          a generated image or video (url under /media/)
  {"type": "error", "text": "..."}
  {"type": "done"}
"""
import base64
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
from PIL import Image
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from media_tools import MEDIA_DIR, MEDIA_TOOLS, _out_path, execute_media_tool, translate  # noqa: E402
import poster_text  # noqa: E402

MODELS = os.environ.get("MINIMIND_ASSISTANT_MODELS", os.path.join(ROOT, "assistant", "models"))
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "mistral")
FONG_MODEL = os.environ.get("FONG_MODEL", "fongai")   # our own fine-tune, built by finetune/run.sh
OLLAMA_IDS = {"mistral": OLLAMA_MODEL, "fong4": FONG_MODEL}   # app model id -> Ollama model name
VISION_MODEL = os.environ.get("VISION_MODEL", "qwen2.5vl:7b")   # answers when the user attaches photos
# Optional "Continue with Google": create an OAuth client ID (type "Web application") at
# https://console.cloud.google.com/apis/credentials with authorized JavaScript origin http://localhost:8000
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
DEVICE = "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")
QUERY_PROMPT = "Represent this sentence for searching relevant passages: "  # mxbai query prefix
SYSTEM_PROMPT = ("You are {name}, a helpful assistant made by Fong. If asked who you are or which model you are, "
                 "say you are {name}; never call yourself Mistral or Qwen or mention Ollama. You can create pictures with generate_image and short clips with "
                 "generate_video; call them only when the user asks for an image, picture, drawing, photo, logo, icon, PNG, poster or video, "
                 "and write the prompt argument in English. When they ask for one, call the tool right away with your own good design "
                 "choices (subject, style, colors, background) even if the request is short; never ask for more details first and "
                 "never say you can't create images. Otherwise just answer.")
# Photo + "make one like this": the vision model turns the photo's style into a prompt for the image generator.
VISION_PROMPT_WRITER = ("Write ONE English prompt (at most 60 words) for an image generator that will create what the user asks for, "
                        "matching the style of the attached image: subject, art style (e.g. flat, 3D, glossy, line art), colors, lighting "
                        "and background. If the user wants a logo or icon, describe a single centered icon on a plain white background. "
                        "Output only the prompt, no quotes or explanations.\n\nUser's request: ")
IMAGE_WORDS = re.compile(r"\b(generate|create|make|draw|design|paint|render)\b.*\b(image|picture|photo|logo|icon|png|poster|"
                         r"drawing|art|wallpaper|sticker|banner|one|it|this|version)\b|\blike ?this\b|\bsimilar\b|\bpng\b|"
                         r"បង្កើត|គូរ|រូបភាព|ឡូហ្គោ|画|生成|设计|图标|图片|标志", re.I)


# Text only: stricter (a verb AND a picture word), so "how do I make it work?" doesn't draw anything.
TEXT_IMAGE_ASK = re.compile(r"\b(generate|create|make|draw|design|paint|render|give me)\b.{0,40}\b(image|picture|photo|logo|icon|"
                            r"png|poster|drawing|wallpaper|sticker|banner|illustration)s?\b|^(an? )?(image|picture|logo|icon) of\b|"
                            r"^(please |pls |can you |could you |help me |me )*(draw|paint|sketch)\b|"
                            r"(បង្កើត|គូរ).{0,20}(រូបភាព|ឡូហ្គោ|រូប)|^គូរ|帮我画|画一|(生成|设计|做).{0,10}(图|图标|图片|标志|logo)", re.I)
HOW_TO = re.compile(r"^\s*(how (do|can|to|would|should)|what('s| is)|why|where|which|explain|tutorial)\b|^如何|^怎么|^តើ.*(ដូចម្តេច|របៀប)", re.I)
PROMPT_WRITER = ("Write ONE English prompt (at most 60 words) for an image generator for the user's request below. Make good design "
                 "choices yourself: subject, art style, colors, lighting, background. For a logo or icon: a single centered icon, "
                 "clean modern style, plain white background. Output only the prompt.\n\nUser's request: ")


def wants_image(text):
    return bool(IMAGE_WORDS.search(text))


POSTER_ASK = re.compile(r"\b(poster|flyer|banner|brochure|cover|thumbnail|ad|advert|menu|card)s?\b|ផ្ទាំង|海报", re.I)
# "modify / edit / fix this" with a photo: change that picture (img2img) instead of drawing a new one from scratch
EDIT_ASK = re.compile(r"\b(modify|edit|change|fix|improve|update|enhance|adjust|redo|retouch|recolou?r|turn (it|this))\b|"
                      r"\bmake (it|this)\b|កែ|修改|改", re.I)
EDIT_PROMPT_WRITER = ("Write ONE English prompt (at most 60 words) for an image generator that will redraw the attached image with the "
                      "user's changes applied. Describe the final picture: layout, main objects, art style, colors, lighting, "
                      "background. Keep everything the user didn't ask to change. Output only the prompt, no quotes or explanations."
                      "\n\nUser's request: ")
POSTER_PLANNER = """A user wants to change the words on their poster. These are the text lines on it now:
{lines}

Earlier messages from the user:
{earlier}

The user's newest message: {ask}

Reply with JSON only: {{"changes": [{{"line": <line number>, "new": "<new text for that line>"}}], "ask": ""}}
Rules:
- Change only the lines the user gives new words, numbers or dates for. Use their exact words and numbers.
- Match each new value to the line it replaces: a new title replaces the title line, a new discount goes into the
  discount line (keep its other words, e.g. "Discount up to 70%"), new dates replace the date line.
- Never change the shop or brand name unless the user names a new one.
- Keep each new line in the same style as the old one (same capital letters, same date format).
- Never invent sale names, discounts, prices or dates. "new": "" removes a line.
- If the user wants new text but doesn't say what it should be, return no changes and put in "ask" one short question
  asking for the new text."""
POSTER_PLAN_MODEL = os.environ.get("POSTER_PLAN_MODEL", VISION_MODEL)   # Qwen follows these rules far better than Mistral
REMOVE_ASK = re.compile(r"\b(remove|delete|erase|drop|get rid of|without)\b|លុប|删", re.I)
POSTER_MARK = "on your poster"   # every poster reply says this, so a text-only follow-up continues the edit
POSTER = {}   # the poster being edited: {"image", "lines", "changes"} (local app, one user)


def plan_poster(ask, earlier):
    """Ask the text model which lines to rewrite. Returns ({line index: new text}, question)."""
    current = [POSTER["changes"].get(i, l["text"]) for i, l in enumerate(POSTER["lines"])]
    def describe(i, t):
        h = poster_text._geometry(POSTER["lines"][i]["quad"])[1] / POSTER["image"].height
        return f"{i}: {t}" + ("   (big headline)" if h > 0.12 else "   (small print)" if h < 0.05 else "")
    prompt = POSTER_PLANNER.format(lines="\n".join(describe(i, t) for i, t in enumerate(current)),
                                   earlier="\n".join(earlier) or "(none)", ask=ask)
    r = requests.post(f"{OLLAMA_URL}/api/chat", timeout=300, json={
        "model": POSTER_PLAN_MODEL, "stream": False, "format": "json", "options": {"temperature": 0},
        "messages": [{"role": "user", "content": prompt}]})
    r.raise_for_status()
    try:
        plan = json.loads(r.json()["message"]["content"])
    except (ValueError, KeyError):
        return {}, ""
    # The model sometimes invents text: every word and number it writes must come from the user or the old line.
    said = set(re.findall(r"\w+", (ask + " " + " ".join(earlier)).lower()))
    changes = {}
    for c in plan.get("changes") or []:
        try:
            i, new = int(c["line"]), str(c.get("new", "")).strip()
        except (KeyError, TypeError, ValueError):
            continue
        if not (0 <= i < len(current)) or new == current[i]:
            continue
        if not new and not REMOVE_ASK.search(ask):
            continue
        if all(w in said or w in current[i].lower() for w in re.findall(r"\w+", new.lower())):
            old_letters = [ch for ch in current[i] if ch.isalpha()]
            changes[i] = new.upper() if old_letters and all(ch.isupper() for ch in old_letters) else new   # MEGA SALE style
    return changes, str(plan.get("ask") or "").strip()


def poster_events(ask, earlier, follow_up=False):
    """Rewrite words on POSTER["image"] in a real font; the rest of the picture is untouched.
    Returns False (having shown nothing) when a follow-up message isn't about the poster after all."""
    yield {"type": "status", "text": "Planning the new text..."}
    changes, question = plan_poster(ask, earlier)
    current = [POSTER["changes"].get(i, l["text"]) for i, l in enumerate(POSTER["lines"])]
    if not changes and follow_up:   # not about the poster: let the normal chat answer
        return False
    if not changes:
        listing = "\n".join(f"- {t}" for t in current)
        yield {"type": "text", "delta": f"{question or 'What should the new text say?'}\n\nThis is the text {POSTER_MARK} now:\n\n"
                                        f"{listing}\n\nTell me the new words, e.g. *title: YEAR END SALE, discount: 70%, "
                                        f"dates: 12 Dec - 15 Dec 2026*."}
        return True
    POSTER["changes"].update(changes)
    yield {"type": "status", "text": "Writing the new text..."}
    out = poster_text.replace_text(POSTER["image"], POSTER["lines"], POSTER["changes"])
    path = _out_path("image", "png")
    out.save(path)
    done = "\n".join(f"- {current[i] or '(empty)'} → {new or '(removed)'}" for i, new in changes.items())
    yield {"type": "media", "item": media_item(path, "image", "Edited poster")}
    yield {"type": "text", "delta": f"Changed {POSTER_MARK}:\n\n{done}\n\nEverything else is untouched. "
                                    "Want another change? Just tell me the new words."}
    return True


ICON_ASK = re.compile(r"\b(logo|icon|app icon|favicon|emblem|badge)s?\b|ឡូហ្គោ|图标|标志|logo", re.I)


def icon_style(draw, question):
    """SDXL-Turbo draws a whole sheet of icons unless told otherwise."""
    if ICON_ASK.search(question) and not POSTER_ASK.search(question):
        draw += (", ONE single icon only, one object, centered, isolated on plain white background, app icon, "
                 "high quality vector style, no text, no grid, no collage")
    return draw


VISION_SYSTEM = ("You are Fong AI, a helpful assistant made by Fong. Never call yourself Qwen. Look carefully at the attached "
                 "image(s) and answer the user's question about them. Reply in the user's language (English, Khmer, Chinese, ...). "
                 "Never say you can't create images: Fong AI can (the app does it when the user asks to make one).")
MODEL_INFO = [
    {"id": "fong4", "name": "FongAI 4", "detail": "Our own model · creates images and videos"},
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
    for name in set(OLLAMA_IDS.values()) | {VISION_MODEL}:
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


def run_tool(name, args, init_image=None, caption=None):
    """Generator: progress events, then a media or error event. Returns the tool result dict.
    Generation runs in a thread so the percentage can stream while it works. caption: what the chat shows
    under the picture (the prompt without technical add-ons)."""
    kind = "image" if name == "generate_image" else "video"
    label = "Creating image" if kind == "image" else "Creating video (can take several minutes)"
    yield {"type": "status", "text": label}
    state = {"floor": 0.0, "cap": 0.05}
    box = {}

    def report(floor, cap):
        state["floor"], state["cap"] = floor, max(floor, cap)

    def work():
        box["result"] = execute_media_tool(name, args, progress=report, init_image=init_image)
    t = Thread(target=work, daemon=True)
    t.start()
    shown, ease = 0.0, 0.06 if kind == "image" else 0.01   # creep toward the stage's cap between real updates
    yield {"type": "progress", "kind": kind, "value": 0}
    while t.is_alive():
        t.join(0.4)
        shown = max(shown, state["floor"], shown + (state["cap"] - shown) * ease)
        yield {"type": "progress", "kind": kind, "value": min(99, int(shown * 100))}
    result = box.get("result") or {"error": f"unknown tool {name}"}
    yield {"type": "status", "text": ""}
    if "path" in result:
        item = media_item(result["path"], result.get("type"), caption or result.get("prompt"))
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


def answer_vision(messages, temperature, max_new, images):
    """Photos attached: a vision model reads them. 16GB can't hold two 7B models, so free the chat model first."""
    for name in set(OLLAMA_IDS.values()):
        try:
            requests.post(f"{OLLAMA_URL}/api/generate", json={"model": name, "keep_alive": 0}, timeout=30)
        except Exception:
            pass
    msgs = [{"role": "system", "content": VISION_SYSTEM}] + messages[:-1] + [dict(messages[-1], images=images)]
    body = {"model": VISION_MODEL, "messages": msgs, "stream": True,
            "options": {"temperature": temperature, "num_predict": max_new}}
    r = requests.post(f"{OLLAMA_URL}/api/chat", json=body, stream=True, timeout=600)
    r.raise_for_status()
    for line in r.iter_lines():
        piece = json.loads(line).get("message", {}).get("content", "") if line else ""
        if piece:
            yield {"type": "text", "delta": piece}


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
    messages: list[dict]            # [{"role": "user"|"assistant", "content": str}, ...]; last one is the question,
                                    # optionally with "images": [data URL or base64, ...] (photos to look at)
    model: str = "fong4"
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

    images = [i.split(",", 1)[-1] for i in req.messages[-1].get("images") or []]   # strip "data:image/...;base64,"
    if images:
        if not ollama_ok(VISION_MODEL):
            yield {"type": "error", "text": f"Photo understanding isn't installed yet. Run: ollama pull {VISION_MODEL}"}
            return
        yield {"type": "status", "text": "Looking at your photo..."}
        asked = translate(question, "English") if is_khmer(question) else question
        if EDIT_ASK.search(asked) or POSTER_ASK.search(asked):   # posters: swap the words, don't redraw
            photo = Image.open(io.BytesIO(base64.b64decode(images[0]))).convert("RGB")
            yield {"type": "status", "text": "Reading the text on your poster..."}
            lines = poster_text.find_text(photo)
            if lines:
                POSTER.clear()
                POSTER.update(image=photo, lines=lines, changes={})
                yield from poster_events(asked, [])
                return
        if wants_image(question):   # "make a logo like this": describe its style, then draw a new one
            asked = translate(question, "English") if is_khmer(question) else question
            edit = bool(EDIT_ASK.search(asked))
            writer = EDIT_PROMPT_WRITER if edit else VISION_PROMPT_WRITER
            draw = "".join(ev["delta"] for ev in answer_vision(
                [{"role": "user", "content": writer + asked}], 0.4, 160, images)).strip().strip('"')
            unload_ollama()   # free the vision model before the image model loads (16GB)
            yield {"type": "text", "delta": f"{'Here is what I will change' if edit else 'Here is my design idea'}:\n\n> {draw}\n\n"}
            photo = Image.open(io.BytesIO(base64.b64decode(images[0]))) if edit else None
            result = yield from run_tool("generate_image", {"prompt": icon_style(draw, question)}, init_image=photo, caption=draw)
            if "seconds" in result:
                note = (" The image model can't write readable text, so add the words (like dates and prices) in a design "
                        "app afterwards." if POSTER_ASK.search(asked) else "")
                yield {"type": "text", "delta": f"Here is your PNG ({result['seconds']}s).{note} Want changes? Tell me what to adjust."}
            return
        first = True
        for ev in answer_vision(history + [{"role": "user", "content": question}], req.temperature, req.max_new, images):
            if first:
                yield {"type": "status", "text": ""}
                first = False
            yield ev
        return

    last_reply = next((m["content"] for m in reversed(history) if m["role"] == "assistant"), "")
    if POSTER and POSTER_MARK in last_reply:
        asked = translate(question, "English") if is_khmer(question) else question
        earlier = [m["content"] for m in history if m["role"] == "user"][-3:]
        if (yield from poster_events(asked, earlier, follow_up=True)):
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
    if mistral and req.use_tools and TEXT_IMAGE_ASK.search(question) and not HOW_TO.search(question):   # draw it, don't ask questions back
        yield {"type": "status", "text": "Designing your image..."}
        asked = translate(question, "English") if is_khmer(question) else question
        ctx = [m for m in history if m["role"] == "user"][-2:]   # earlier details ("blue", "for my shop", ...)
        draw = "".join(ev.get("delta", "") for ev in answer_ollama(
            ctx + [{"role": "user", "content": PROMPT_WRITER + asked}], 0.5, 160, False, name=ollama_name)).strip().strip('"')
        unload_ollama()
        yield {"type": "status", "text": ""}
        yield {"type": "text", "delta": f"Here's my design idea:\n\n> {draw}\n\n"}
        result = yield from run_tool("generate_image", {"prompt": icon_style(draw, question)}, caption=draw)
        if "seconds" in result:
            yield {"type": "text", "delta": f"Here is your image ({result['seconds']}s). Want changes? Tell me what to adjust."}
        return
    khmer = is_khmer(question) and mistral   # FongAI 4 knows its name in Khmer but gets Khmer facts wrong, so translate too
    asked = question
    if khmer:  # the Ollama models understand Khmer poorly: translate in, answer in English, translate back
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
