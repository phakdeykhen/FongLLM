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
from PIL import Image, ImageFilter
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from media_tools import MEDIA_DIR, MEDIA_TOOLS, _out_path, execute_media_tool, translate  # noqa: E402
import poster_text  # noqa: E402
import promo_poster  # noqa: E402
import file_tools  # noqa: E402
import google_tools  # noqa: E402
import design  # noqa: E402
import design_catalog  # noqa: E402
import design_style  # noqa: E402
import vector_store  # noqa: E402
import media_tools  # noqa: E402

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
                 "never say you can't create images. You have no access to Google Drive, Google Sheets, Google Docs, email or "
                 "the internet. Never say you created, saved, sent or shared a file, sheet or document: the app builds real "
                 "files itself and shows them with a preview. If the user wants one, tell them to ask like: "
                 "'create an Excel sheet of my monthly expenses'. Otherwise just answer.")
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
FOLLOW_TITLE = re.compile(r"^\s*(tit+le|name|call it)\b", re.I)   # "Title: kimi" after asking for a file
# "add a person / remove the arrow" with a photo: also a redraw (kept out of EDIT_ASK so "create a poster, add $10" stays a poster)
ADD_ASK = re.compile(r"\b(add|remove|replace|erase|delete|put|insert|swap)\b|បន្ថែម|ដក|添加|加上|去掉|删除", re.I)
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
# "create a promotion for this set, $10 only" + a product photo: build a sale poster around the real product
PROMO_ASK = re.compile(r"\b(promo(tion)?s?|sale|offer|discount|deal|advert\w*|ads?|marketing|price)\b|\$\s?\d|\d\s?\$|"
                       r"ប្រូម៉ូសិន|ផ្សព្វផ្សាយ|តម្លៃ|促销|优惠|广告", re.I)
CREATE_VERB = re.compile(r"\b(create|make|design|generate|build|do|need|want)\b|បង្កើត|ធ្វើ|做|设计|生成", re.I)
# a short "yes" to an offer ("yes please", "ok do it"); "Please create a POS app" is a new request, not a yes
YES = re.compile(r"^\s*((yes|yeah|yep|ok(ay)?|sure|go ahead|do it|let'?s (go|do it)|ចាស|បាទ)\b[\s,.!]*(please|pls|do it|go ahead|thanks?)?[\s.!]*$"
                 r"|please[\s.!]*$|(好|好的|可以)[\s。！!]*$)", re.I)
OFFERED_VISUAL = re.compile(r"\b(visual|image|poster|picture|design|flyer|banner)\b", re.I)
PRODUCT_READER = """This photo shows a product the user wants to promote. The user said: {ask}
Earlier in the chat:
{earlier}

Reply with JSON only:
{{"title": "brand + product name for the poster headline, max 5 words, e.g. ANUA Heartleaf Skincare Set",
  "headline": "short offer label without the price, max 3 words, e.g. SPECIAL OFFER",
  "tagline": "one short benefit line, max 8 words",
  "items": ["short names of the separate products, max 6, max 4 words each, copied from the labels or from the earlier
             chat; [] for a single product or when you can't read them"],
  "price": "the price the user gave, exactly as written, or empty",
  "cta": "call to action, max 3 words, e.g. Order now"}}
Only use brand names you can actually read on the photo. Never invent a price or discount.
Write title, headline, tagline, items and cta in the user's language."""


def read_product(image_b64, ask, earlier):
    """Vision model -> poster wording for the product photo ({} if it fails)."""
    body = {"model": VISION_MODEL, "stream": False, "format": "json", "options": {"temperature": 0.2, "num_predict": 400},
            "messages": [{"role": "user", "content": PRODUCT_READER.format(ask=ask, earlier="\n".join(earlier) or "-"),
                          "images": [image_b64]}]}
    try:
        r = requests.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=300)
        r.raise_for_status()
        info = json.loads(r.json()["message"]["content"])
        return info if isinstance(info, dict) else {}
    except Exception:
        return {}


def promo_events(image_b64, ask, history):
    """Sale poster from the user's own product photo: the product is cut out (never redrawn), the words are typeset
    in a real font, and the image model only paints the empty backdrop. history: recent messages (an earlier reply
    may already list the set's products by name)."""
    yield {"type": "status", "text": "Reading your product..."}
    said = [m["content"] for m in history if m["role"] == "user"][-3:]
    info = read_product(image_b64, ask, [f"{m['role']}: {m['content'][:700]}" for m in history[-4:]])
    unload_ollama()   # free the vision model before the image model loads (16GB)
    text = lambda k: str(info.get(k) or "").strip()
    price = promo_poster.find_price(ask) or promo_poster.find_price(" ".join(reversed(said))) or text("price")
    photo = Image.open(io.BytesIO(base64.b64decode(image_b64))).convert("RGB")
    backdrop = None
    result = yield from run_tool("generate_image", {"prompt": promo_poster.backdrop_prompt(photo)}, show=False)
    if "path" in result:
        backdrop = Image.open(result["path"]).filter(ImageFilter.GaussianBlur(4))   # reads as depth of field
    yield {"type": "status", "text": "Laying out your poster..."}
    items = [str(i).strip() for i in info.get("items") or [] if str(i).strip()]
    headline = text("headline")
    if not headline or re.search(r"\d", headline):   # the price has its own badge; don't print it twice
        headline = "SPECIAL OFFER"
    out = promo_poster.make_poster(photo, title=text("title"), price=price, headline=headline,
                                   tagline=text("tagline"), items=items if len(items) > 1 else [],
                                   cta=text("cta") or "Order now", backdrop=backdrop)
    path = _out_path("image", "png")
    out.save(path)
    yield {"type": "status", "text": ""}
    yield {"type": "media", "item": media_item(path, "image", f"{text('title') or 'Promotion poster'} {price}".strip())}
    missing = "" if price else " Tell me the price and I'll add it."
    yield {"type": "text", "delta": "Here is your promotion poster, made with your real product photo so the products and "
                                    f"labels stay exactly right.{missing} Want changes? Tell me the new title, price or "
                                    "wording."}


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
    # drop "changes" that keep the same words (the planner sometimes echoes a line back)
    changes = {i: t for i, t in changes.items()
               if not (0 <= i < len(current) and (t or "").strip().lower() == (current[i] or "").strip().lower())}
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


FILE_EDIT = re.compile(r"\b(change|edit|update|fix|add|remove|delete|replace|set|make|put|move|rename|translate|shorten|"
                       r"expand|instead|more|less|bigger|smaller)\b|កែ|ប្តូរ|修改|改", re.I)


def file_events(kind, ask, history, model_id, revise=False):
    """'create a quotation as PDF' -> the chat model writes the content, Python builds the real file + preview."""
    name = OLLAMA_IDS.get(model_id)
    if not name or not ollama_ok(name):   # the tiny 64M model can't write files: use an Ollama model that is installed
        name = next((n for n in (FONG_MODEL, OLLAMA_MODEL) if ollama_ok(n)), None)
    if not name:
        yield {"type": "error", "text": "Making files needs an Ollama model. Run: brew services start ollama && ollama pull mistral"}
        return
    label = file_tools.KINDS[kind]["label"]
    verb = "Updating" if revise else "Writing"
    yield {"type": "status", "text": f"{verb} your {label} file..."}
    words = []

    def progress(n):
        words.append(n)
    import threading
    out, err = {}, {}

    def work():
        try:
            out["src"] = file_tools.write_source(kind, ask, OLLAMA_URL, name, history, revise, progress)
        except Exception as e:   # noqa: BLE001
            err["e"] = e
    t = threading.Thread(target=work)
    t.start()
    shown = 0
    while t.is_alive():
        t.join(0.5)
        if words and words[-1] != shown:
            shown = words[-1]
            yield {"type": "status", "text": f"{verb} your {label} file... {shown} words"}
    if err:
        raise err["e"]
    src = out.get("src", "").strip()
    if not src:
        yield {"type": "error", "text": "The model returned nothing. Please try again."}
        return
    yield {"type": "status", "text": f"Building the {label} file..."}
    # "Do the same as a Google Sheet" / "please create now": name it after the real request, "Title: kimi" -> "kimi"
    named = FOLLOW_TITLE.match(ask)
    title = ask[named.end():].strip(" :=-\"'") if named else ask
    if not named and len(ask.split()) <= 6:
        title = next((m["content"] for m in reversed(history[-6:]) if m["role"] == "user"
                      and m["content"] != ask and file_tools.detect_kind(m["content"])), ask)
    item = file_tools.build_file(kind, src, fallback_title=(title or ask)[:50])
    yield {"type": "file", "item": item}
    what = "updated" if revise else "made"
    yield {"type": "text", "delta": f"I {what} **{item['title']}** as {'an' if label[0] in 'AEIOU' else 'a'} {label} file. {file_tools.FILE_MARK}, "
                                    "or download it. Want changes? Just tell me what to change."}
    asked_google = [ask] + [m["content"] for m in history[-6:] if m["role"] == "user"]
    if any(file_tools.GOOGLE_ASK.search(t) for t in asked_google):
        app = {"xlsx": "Google Sheets", "docx": "Google Docs", "pptx": "Google Slides"}.get(kind, "Google Drive")
        yield {"type": "text", "delta": (f"\n\nClick **Save to {app}** under the file to create it in your Google "
                                         "Drive (Google asks for your permission the first time)." if GOOGLE_CLIENT_ID else
                                         f"\n\n**To open it in {app}:** download it, go to drive.google.com, click "
                                         "**New → File upload**, then open it with {app}.".replace("{app}", app))}


DESIGN_PLANNER = """You design a {name} ({size}). From the user's request or brief, write its words and pick its picture.
Reply with JSON only:
{{"brand": "brand, shop or product name (short; empty if none)",
  "eyebrow": "small label above the headline, max 5 words (an offer, event name, program name or 'New')",
  "headline": "the main message, {words} punchy words",
  "highlight": "1-2 words from the headline to color (the key benefit)",
  "subheadline": "one sentence, max 20 words, the concrete value or details (date, place, price) from the request",
  "features": ["2-4 very short selling points, max 3 words each, only from the request"],
  "cta": "button text, 2-3 words",
  "color": "#hex brand color that fits the topic (coffee = brown, nature = green, tech = blue, sale = red, luxury = black or gold)",
  "hero": "the photo: a PERSON or a real OBJECT, concrete and visual (e.g. 'a cup of iced latte on a wooden cafe table', 'a smiling bride and groom'). Never a sign, screen, poster or anything with words"}}
Use only facts from the request: don't invent prices, dates, phone numbers or claims. Write in English.

Request:
{ask}"""
REDESIGN = re.compile(r"\b(redesign|re-design|remake|rebuild|recreate|new design|design (it|this)|follow (the |your )?layout|"
                      r"fongai (style|layout)|(into|as|to) (an? )?(\w+ ){0,3}(banners?|posters?|story|stories|posts?|covers?|"
                      r"thumbnails?|flyers?|standees?|backdrops?|roll-?up))\b", re.I)
TEXT_EDIT = re.compile(r"\b(change|replace|fix|update|edit|correct|swap)\b.{0,30}\b(text|words?|price|title|name|date|phone|"
                       r"number|wording|headline)\b", re.I)
STYLE_ASK = re.compile(r"\b(like|same as|similar to|in the style of|style of|follow|copy)\b.{0,20}\b(image|picture|photo|pic|img|"
                       r"design|poster|this|that|second|2nd|first|1st|last)\b|\b(style|look|vibe|theme)\b", re.I)
ORDINALS = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2}


def style_reference(asked, pics):
    """Which attached picture is the style to copy? 'like image 2' / 'the second one'; otherwise, with two or more
    pictures and a style request, the one with the most text on it (a finished design), else the last one."""
    if len(pics) < 2:
        return 0 if len(pics) == 1 and STYLE_ASK.search(asked) and REFERENCE_ONLY.search(asked) else None
    m = re.search(r"\b(?:image|picture|photo|pic|img|design|no\.?|#)\s*(\d)\b", asked, re.I)
    if m and 1 <= int(m.group(1)) <= len(pics):
        return int(m.group(1)) - 1
    m = re.search(r"\b(first|1st|second|2nd|third|3rd)\b", asked, re.I)
    if m and ORDINALS[m.group(1).lower()] < len(pics):
        return ORDINALS[m.group(1).lower()]
    if re.search(r"\blast\b", asked, re.I):
        return len(pics) - 1
    words = [sum(len(l["text"].split()) for l in poster_text.find_text(p)) for p in pics]
    best = max(range(len(pics)), key=lambda i: words[i])
    return best if words[best] >= words[-1] + 4 else len(pics) - 1


REFERENCE_ONLY = re.compile(r"\b(style|look|vibe|theme)\b", re.I)   # one picture + "in this style": a reference, no product
HEADLINE_WORDS = {"thumb": "2-4", "repeat": "1-3", "tall": "3-6", "banner": "3-8", "square": "3-7", "poster": "3-7"}
SOON = {"card": "cards (business cards, invitations, vouchers, ID cards)", "certificate": "certificates",
        "infographic": "infographics and charts", "carousel": "carousels", "sign": "signs", "frame": "photo frames",
        "icon": "highlight covers", "artwork": "packaging, labels, uniforms and other print artwork"}


def _png_bytes(img):
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def design_events(entry, ask, history, name, photo=None, style_ref=None):
    """Any catalog design (banner, poster, story, standee, thumbnail...): the model writes the words, the image model
    paints only the photo, and design.py lays it out at the exact size with real fonts (sharp, correctly spelled)."""
    layout, (w, h) = entry["layout"], entry["size"]
    khmer = is_khmer(ask)
    asked = translate(ask, "English") if khmer else ask
    # An attached picture: the user's own photo goes into the design as it is; a finished design (lots of text,
    # e.g. a banner made elsewhere) is read and rebuilt in FongAI's layout with its words and colors.
    own_photo, reference, color, style = None, "", None, None
    if style_ref is not None:   # "like image 2": copy that design's look; the other picture is the product
        yield {"type": "status", "text": "Studying the style you showed me..."}
        b64 = base64.b64encode(_png_bytes(style_ref)).decode()
        style = design_style.read_style(style_ref, lambda q: "".join(
            ev.get("delta", "") for ev in answer_vision([{"role": "user", "content": q}], 0.1, 200, [b64])))
        unload_ollama()   # free the vision model
    product_words = ""
    if style is not None and photo is not None:
        product_words = " / ".join(dict.fromkeys(l["text"] for l in poster_text.find_text(photo)))[:200]
        yield {"type": "status", "text": "Cutting out your product..."}
        own_photo = promo_poster.ai_cutout(photo) or promo_poster.cutout(photo) or promo_poster.card(photo).convert("RGBA")
    elif photo is not None:
        yield {"type": "status", "text": "Reading your picture..."}
        lines = poster_text.find_text(photo)
        if sum(len(l["text"].split()) for l in lines) >= 6:
            reference = "\n".join(l["text"] for l in lines[:40])
        else:
            own_photo = photo
        small = photo.copy()
        small.thumbnail((256, 256))
        color = "#%02x%02x%02x" % promo_poster.accent_color(small)
    yield {"type": "status", "text": f"Designing your {entry['name']}..."}
    earlier = [m["content"][:600] for m in history[-4:] if m["role"] == "user"]
    if reference:
        asked += ("\n\nThe user attached an existing design to rebuild in this format. Keep its brand, message, offer "
                  "and details. The words on it:\n" + reference)
    prompt = DESIGN_PLANNER.format(name=entry["name"], size=f"{w}x{h} px",
                                   words="2-4" if style is not None else HEADLINE_WORDS.get(layout, "3-7"),
                                   ask="\n".join(earlier + [asked]))
    if style is not None:
        prompt += ("\n\nThe look is copied from another poster, but the TOPIC comes only from the user's request and their "
                   "product. Make 'highlight' ONE short fun word that is NOT in the headline (like 'relax', 'new!', 'yum').")
    if product_words:
        prompt += f"\n\nWords printed on the user's product (use the brand name from here): {product_words}"
    r = requests.post(f"{OLLAMA_URL}/api/chat", timeout=300, json={
        "model": name, "stream": False, "format": "json", "options": {"temperature": 0.4},
        "messages": [{"role": "user", "content": prompt}]})
    r.raise_for_status()
    m = re.search(r"\{.*\}", r.json().get("message", {}).get("content", ""), re.S)
    try:
        plan = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        plan = {}
    if khmer:   # the words in Khmer; the picture prompt stays English
        yield {"type": "status", "text": "Translating the words to Khmer..."}
        for k in ("eyebrow", "headline", "subheadline", "cta"):
            if plan.get(k):
                plan[k] = translate(str(plan[k]), "Khmer")
        plan["highlight"] = ""
        plan["features"] = [translate(str(f), "Khmer") for f in plan.get("features") or []][:4]
    if color:
        plan["color"] = color   # match the attached picture
    unload_ollama()   # free the chat model before the image model loads (16GB)
    hero = own_photo
    if hero is None and layout != "repeat":   # a step-and-repeat wall is only the brand, tiled
        subject = str(plan.get("hero") or plan.get("headline") or asked)[:300]
        prompt = (design.hero_prompt(subject, layout) if style is None else
                  f"{subject}, single product, isolated on a plain white background, studio product photography, no text")
        result = yield from run_tool("generate_image", {"prompt": prompt}, show=False)
        if "path" in result:
            hero = Image.open(result["path"]).convert("RGB")
            if style is not None:
                hero = promo_poster.ai_cutout(hero) or promo_poster.cutout(hero) or hero.convert("RGBA")
    if style is not None and entry["layout"] not in ("poster", "square", "tall"):
        (w, h) = (1697, 2400)   # the styled layout is a portrait poster
    yield {"type": "status", "text": f"Laying out your {entry['name']}..."}
    path = _out_path("image", "png")
    design.make_design(plan, hero, layout, (w, h), style=style).save(path)
    yield {"type": "status", "text": ""}
    yield {"type": "media", "item": media_item(path, "image", f"{entry['name']}: {plan.get('headline') or ''}".strip(": "))}
    yield {"type": "text", "delta": f"Here is your **{entry['name']}** ({w}×{h}). The words are typeset in a real font, so "
                                    "they're sharp and spelled right. Want changes? Tell me a new headline, button, color "
                                    "or picture."}


def design_soon(entry):
    """Catalog types without their own layout yet: say so honestly and offer the closest one."""
    kind = entry["layout"].split(":", 1)[1]
    yield {"type": "text", "delta": f"A dedicated **{entry['name']}** layout isn't ready yet: FongAI's designs for "
                                    f"{SOON.get(kind, kind)} are coming next. For now I can make it as a **poster** "
                                    f"or a **square post** with the same words. Just say \"make it a poster\"."}


def google_events(kind, ask, history, model_id):
    """Gmail draft / Calendar event / Maps link: the model fills it in, the browser shows a card to check and confirm."""
    name = OLLAMA_IDS.get(model_id)
    if not name or not ollama_ok(name):
        name = next((n for n in (FONG_MODEL, OLLAMA_MODEL) if ollama_ok(n)), None)
    if not name:
        yield {"type": "error", "text": "This needs an Ollama model. Run: brew services start ollama"}
        return
    yield {"type": "status", "text": {"gmail": "Writing your email...", "calendar": "Planning your event...",
                                      "maps": "Finding it on the map..."}[kind]}
    khmer = is_khmer(ask)   # the chat models write poor Khmer: write in English, then translate
    try:
        card = google_tools.prepare(kind, translate(ask, "English") if khmer else ask, history, OLLAMA_URL, name)
        if khmer and kind == "gmail":
            yield {"type": "status", "text": "Translating to Khmer..."}
            card["subject"] = translate(card["subject"], "Khmer") if card["subject"] else ""
            card["body"] = translate(card["body"], "Khmer") if card["body"] else ""
    except Exception as e:   # noqa: BLE001
        yield {"type": "error", "text": f"Couldn't prepare that: {str(e)[:150]}"}
        return
    yield {"type": "status", "text": ""}
    yield {"type": "text", "delta": google_tools.INTRO[kind]}
    yield {"type": "google", "item": card}


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


VOICE_SYSTEM = (" This is a spoken voice conversation: your reply will be read aloud. Answer in 1-3 short, natural "
                "sentences, like talking to a friend. No markdown, lists, headings, emoji or code.")

# Khmer text-to-speech for voice mode (Meta MMS-TTS, CC-BY-NC 4.0: non-commercial use only).
# Other languages are spoken by the browser's own voices.
KHMER_TTS_MODEL = os.environ.get("KHMER_TTS_MODEL", "facebook/mms-tts-khm")
KHMER_SAY = {"fong ai": "ហ្វុង អេអាយ", "fongai": "ហ្វុង អេអាយ", "fong": "ហ្វុង", "ai": "អេអាយ"}   # it can't read Latin letters


@lru_cache(maxsize=1)
def load_khmer_tts():
    from transformers import AutoTokenizer, VitsModel
    return AutoTokenizer.from_pretrained(KHMER_TTS_MODEL), VitsModel.from_pretrained(KHMER_TTS_MODEL).eval()


# whisper-large-v2 hears Khmer as Vietnamese/Thai, so Khmer voice uses a Whisper fine-tuned on Khmer speech
KHMER_ASR_MODEL = os.environ.get("KHMER_ASR_MODEL", "seanghay/whisper-medium-khmer")


@lru_cache(maxsize=1)
def load_khmer_whisper():
    from transformers import GenerationConfig, pipeline
    p = pipeline("automatic-speech-recognition", model=KHMER_ASR_MODEL,
                 dtype=torch.float16 if DEVICE != "cpu" else torch.float32, device=DEVICE)
    # its generation config predates transformers' language/task options: use the matching OpenAI one
    base = {"small": "openai/whisper-small", "base": "openai/whisper-base", "tiny": "openai/whisper-tiny",
            "large": "openai/whisper-large-v2"}
    size = next((v for k, v in base.items() if k in KHMER_ASR_MODEL.lower()), "openai/whisper-medium")
    p.model.generation_config = GenerationConfig.from_pretrained(size)
    return p


@lru_cache(maxsize=1)
def load_embedder():
    """mxbai-embed-large with plain transformers: CLS-token vector, normalized (what its 1_Pooling config asks for).
    sentence-transformers 2.3.1 can't read that config ("include_prompt"), which broke document upload."""
    from transformers import AutoModel, AutoTokenizer
    path = os.path.join(MODELS, "mxbai-embed-large-v1")
    tok, model = AutoTokenizer.from_pretrained(path), AutoModel.from_pretrained(path).to(DEVICE).eval()

    class Embedder:
        def encode(self, texts, normalize_embeddings=True, batch_size=16):
            out = []
            for i in range(0, len(texts), batch_size):
                batch = tok(texts[i:i + batch_size], padding=True, truncation=True, max_length=512, return_tensors="pt").to(DEVICE)
                with torch.no_grad():
                    v = model(**batch).last_hidden_state[:, 0]
                if normalize_embeddings:
                    v = torch.nn.functional.normalize(v, dim=-1)
                out.append(v.float().cpu().numpy())
            return np.concatenate(out) if out else np.zeros((0, model.config.hidden_size), np.float32)
    return Embedder()


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


# ---------- documents: LanceDB on disk (out/vectors), so uploads survive restarts ----------
STORE = vector_store.VectorStore(
    encode=lambda texts: load_embedder().encode(texts, normalize_embeddings=True, batch_size=16),
    encode_query=lambda q: load_embedder().encode([QUERY_PROMPT + q], normalize_embeddings=True)[0])


def retrieve(query, k):
    return STORE.search(query, k)


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


def run_tool(name, args, init_image=None, caption=None, show=True):
    """Generator: progress events, then a media or error event. Returns the tool result dict.
    Generation runs in a thread so the percentage can stream while it works. caption: what the chat shows
    under the picture (the prompt without technical add-ons). show=False: don't send the picture to the chat
    (it's a part of something bigger, like a poster backdrop)."""
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
    if "path" in result and not show:
        pass
    elif "path" in result:
        item = media_item(result["path"], result.get("type"), caption or result.get("prompt"))
        item["seconds"] = result.get("seconds")
        yield {"type": "media", "item": item}
    else:
        yield {"type": "error", "text": result.get("error", "generation failed")}
    return result


# ---------- answer engines (generators of events) ----------
def answer_ollama(messages, temperature, max_new, use_tools, name=OLLAMA_MODEL, extra=""):
    label = next((m["name"] for m in MODEL_INFO if OLLAMA_IDS.get(m["id"]) == name), "Fong AI")
    msgs = [{"role": "system", "content": SYSTEM_PROMPT.format(name=label) + extra}] + messages
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
    image_hd: bool = False          # True: FLUX 1024px (minutes, better); False: sdxl-turbo 512px (seconds)
    voice: bool = False             # voice mode: the reply is read aloud, so keep it short and spoken
    top_k: int = 3


def chat_events(req: ChatRequest):
    media_tools.IMAGE_HD = req.image_hd
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
        # The Edit button on a generated image: always redraw that picture with the requested changes
        edit_image = bool(req.messages[-1].get("edit"))
        # "promotion ... $10" + a product photo is a new sale poster even without a create verb (typos like "creaet")
        if req.use_tools and not edit_image and PROMO_ASK.search(asked) and not EDIT_ASK.search(asked) and (
                CREATE_VERB.search(asked) or POSTER_ASK.search(asked) or promo_poster.find_price(asked)):
            yield from promo_events(images[0], asked, history)
            return
        # "make this into an Instagram story" / "redesign this" / "create a banner with my photo": FongAI's layout system
        wants_design = req.use_tools and not edit_image and not TEXT_EDIT.search(asked) and (
            REDESIGN.search(asked) or (design_catalog.match(asked) and CREATE_VERB.search(asked)))
        if wants_design or (len(images) > 1 and STYLE_ASK.search(asked)):
            pics = [Image.open(io.BytesIO(base64.b64decode(b))).convert("RGB") for b in images[:4]]
            ref_i = style_reference(asked, pics)
            style_ref = pics[ref_i] if ref_i is not None else None
            photo = next((p for i, p in enumerate(pics) if i != ref_i), None)
            entry = design_catalog.match(asked) or design_catalog.for_photo(*(photo or pics[0]).size)
            name = next((n for n in (OLLAMA_IDS.get(req.model), FONG_MODEL, OLLAMA_MODEL) if n and ollama_ok(n)), None)
            if name and (entry["layout"] in design_catalog.DESIGN_LAYOUTS or style_ref is not None):
                unload_ollama()
                yield from design_events(entry, question, history, name, photo=photo, style_ref=style_ref)
                return
        if not edit_image and (EDIT_ASK.search(asked) or POSTER_ASK.search(asked)):   # posters: swap the words, don't redraw
            photo = Image.open(io.BytesIO(base64.b64decode(images[0]))).convert("RGB")
            yield {"type": "status", "text": "Reading the text on your poster..."}
            lines = poster_text.find_text(photo)
            if lines:
                POSTER.clear()
                POSTER.update(image=photo, lines=lines, changes={})
                yield from poster_events(asked, [])
                return
        change_ask = req.use_tools and not HOW_TO.search(question) and (EDIT_ASK.search(asked) or ADD_ASK.search(asked))
        if edit_image or wants_image(question) or change_ask:   # "make a logo like this" / "add a dog to it"
            edit = bool(edit_image or change_ask)
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
    # A product photo sent a moment ago, then "Yes" / "make a poster for it": use that photo, don't draw from scratch
    prev = next((m["images"] for m in reversed(req.messages[-5:-1]) if m.get("role") == "user" and m.get("images")), None)
    if prev and req.use_tools and not HOW_TO.search(question):
        asked = translate(question, "English") if is_khmer(question) else question
        if file_tools.detect_kind(asked):   # "create a React POS app" after a poster: a file, not another poster
            prev = None
    if prev and req.use_tools and not HOW_TO.search(question):
        if ((PROMO_ASK.search(asked) or POSTER_ASK.search(asked)) and CREATE_VERB.search(asked)
                or PROMO_ASK.search(asked) and POSTER_ASK.search(asked) and not EDIT_ASK.search(asked)
                or YES.search(asked) and OFFERED_VISUAL.search(last_reply)
                or "promotion poster" in last_reply and (PROMO_ASK.search(asked) or EDIT_ASK.search(asked))):
            yield from promo_events(prev[0].split(",", 1)[-1], asked, history)
            return
    if POSTER and POSTER_MARK in last_reply:
        asked = translate(question, "English") if is_khmer(question) else question
        earlier = [m["content"] for m in history if m["role"] == "user"][-3:]
        if (yield from poster_events(asked, earlier, follow_up=True)):
            return

    # "write an email to my boss" / "meeting with Dara Friday 3pm" / "directions to the airport": a Google card
    if req.use_tools and not file_tools.detect_kind(question):
        asked = translate(question, "English") if is_khmer(question) else question
        gkind = None if design_catalog.match(asked) else google_tools.detect(asked)
        if gkind:
            yield from google_events(gkind, question, history, req.model)
            return

    # "create a quotation as PDF / an Excel sheet / slides / a React app": build a real file with a preview
    if req.use_tools and not HOW_TO.search(question):
        asked = translate(question, "English") if is_khmer(question) else question
        kind = file_tools.detect_kind(asked)
        if kind:
            yield from file_events(kind, asked, history, req.model)
            return
        if file_tools.LAST and file_tools.FILE_MARK in last_reply and (FILE_EDIT.search(asked) or FOLLOW_TITLE.search(asked)):
            yield from file_events(file_tools.LAST["kind"], asked, history, req.model, revise=True)
            return
        if len(asked.split()) <= 6 and (file_tools.MAKE.search(asked) or FOLLOW_TITLE.search(asked)):
            earlier = next((k for m in reversed(history[-6:]) if m["role"] == "user"
                            for k in [file_tools.detect_kind(m["content"])] if k), None)
            if earlier and file_tools.FILE_MARK not in last_reply:
                yield from file_events(earlier, asked, history, req.model)
                return

    if STORE.passages():
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
    design_type = design_catalog.match(translate(question, "English") if is_khmer(question) else question) \
        if req.use_tools and not HOW_TO.search(question) and (CREATE_VERB.search(question) or TEXT_IMAGE_ASK.search(question)) else None
    if mistral and design_type and design_type["layout"] in design_catalog.DESIGN_LAYOUTS:
        yield from design_events(design_type, question, history, ollama_name)
        return
    if design_type and design_type["layout"].startswith("doc:"):   # brochure, company profile, pitch deck...
        yield from file_events(design_type["layout"][4:], question, history, req.model)
        return
    if design_type and design_type["layout"].startswith("soon:"):
        yield from design_soon(design_type)
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
    extra = VOICE_SYSTEM if req.voice else ""
    engine = (lambda *a: answer_ollama(*a, name=ollama_name, extra=extra)) if mistral else answer_minimind
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
    hd: bool = False


@app.post("/api/image")
def make_image(body: ImageRequest):
    """Generates one image directly (Images page). Same model and folder as /image in chat."""
    if not body.prompt.strip():
        raise HTTPException(400, "Describe the image you want.")
    with GPU_LOCK:
        unload_ollama()
        media_tools.IMAGE_HD = body.hd
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
async def transcribe(file: UploadFile = File(...), language: str = Form("auto")):
    """language: "auto" (any language, whisper-large-v2) or "km" (Khmer model)."""
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
        if language == "km":
            out = load_khmer_whisper()({"raw": data, "sampling_rate": 16000}, chunk_length_s=30,
                                       generate_kwargs={"task": "transcribe", "language": "khmer"})
            # it was trained on word-split text ("មាន ពីរ ប្រភេទ"); written Khmer has no spaces between words
            return {"text": re.sub(r"(?<=[ក-៿])\s+(?=[ក-៿])", "", out["text"]).strip()}
        out = load_whisper()({"raw": data, "sampling_rate": 16000}, chunk_length_s=30, generate_kwargs={"task": "transcribe"})
    return {"text": out["text"].strip()}


class SpeakRequest(BaseModel):
    text: str


@app.post("/api/speak")
def speak(req: SpeakRequest):
    """Khmer text -> WAV (16 kHz). Voice mode plays it."""
    import soundfile as sf
    text = req.text
    for en, km in KHMER_SAY.items():
        text = re.sub(rf"\b{en}\b", km, text, flags=re.I)
    text = re.sub(r"[^\u1780-\u17ff\s។៖!?,.]", " ", text)   # the voice only knows Khmer letters
    parts = [p.strip() for p in re.split(r"(?<=[។?!])\s*|\n+", text) if p.strip()]   # sentence by sentence
    if not parts:
        raise HTTPException(400, "Nothing to say in Khmer.")
    tok, model = load_khmer_tts()
    audio = []
    with GPU_LOCK, torch.no_grad():
        for p in parts[:12]:
            audio.append(model(**tok(p, return_tensors="pt")).waveform[0].numpy())
            audio.append(np.zeros(int(16000 * 0.25), dtype=np.float32))   # a short pause between sentences
    buf = io.BytesIO()
    sf.write(buf, np.concatenate(audio), model.config.sampling_rate, format="WAV")
    return Response(buf.getvalue(), media_type="audio/wav")


@app.get("/api/documents")
def list_documents():
    return {"documents": STORE.documents(), "passages": STORE.passages()}


@app.post("/api/documents")
async def add_documents(files: list[UploadFile] = File(...)):
    for f in files:
        if not f.filename.lower().endswith((".txt", ".md")):
            raise HTTPException(400, f"{f.filename}: only .txt and .md files are supported")
    texts = [(f.filename, (await f.read()).decode("utf-8", errors="ignore")) for f in files]
    with GPU_LOCK:   # only the new documents are embedded; the rest are already on disk
        for name, text in texts:
            STORE.add(name, text)
    return list_documents()


@app.delete("/api/documents/{name}")
def delete_document(name: str):
    STORE.delete(name)
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
os.makedirs(file_tools.FILES_DIR, exist_ok=True)
app.mount("/files", StaticFiles(directory=file_tools.FILES_DIR), name="files")

DIST = os.path.join(ROOT, "web", "dist")
if os.path.isdir(DIST):  # serve the built React app (npm run build) from the same port
    app.mount("/assets", StaticFiles(directory=os.path.join(DIST, "assets")), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        file = os.path.join(DIST, path)
        return FileResponse(file if path and os.path.isfile(file) else os.path.join(DIST, "index.html"))
