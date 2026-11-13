"""
"Make a poster like this one", the way a designer would: as an editable HTML page, rendered to PNG by Chrome.

  1. measure the reference: every text block's exact place and size (design_transfer.analyze, Apple's text reader),
     its background (solid or gradient), the shapes behind text, where the product stands
  2. the local vision model LABELS each numbered block: its role (title, price, tag, faded word...) and lettering
     (serif italic, sans bold, script...). Small models do this well; writing a whole page they don't.
  3. the chat model writes the new words for each block (design_events in server/api.py)
  4. this file writes the HTML (real Mac fonts, CSS shapes, the user's cut-out product) and Chrome renders the PNG.
     The text stays editable in FongAI's preview (click a word to change it).
"""
import html
import json
import os
import re
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from design_transfer import analyze
from poster_text import BOLD_FONT, _font_path

CHROME = os.environ.get("CHROME_BIN", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

# lettering -> CSS (all fonts ship with macOS; Khmer / Chinese fall back to system fonts that have those letters)
FONTS = {
    "serif": ("Didot, 'Bodoni 72', Georgia, serif", 400, "normal"),
    "serif-italic": ("Didot, 'Bodoni 72', Georgia, serif", 400, "italic"),
    "serif-bold": ("'Bodoni 72', Didot, Georgia, serif", 700, "normal"),
    "sans": ("'Helvetica Neue', Helvetica, Arial, sans-serif", 400, "normal"),
    "sans-bold": ("'Helvetica Neue', Helvetica, Arial, sans-serif", 700, "normal"),
    "sans-black": ("'Arial Black', 'Helvetica Neue', sans-serif", 900, "normal"),
    "sans-italic-bold": ("'Helvetica Neue', Helvetica, Arial, sans-serif", 700, "italic"),
    "condensed": ("'DIN Condensed', 'Avenir Next Condensed', 'Arial Narrow', sans-serif", 700, "normal"),
    "script": ("'Snell Roundhand', 'Brush Script MT', cursive", 400, "normal"),
    "handwritten": ("'Marker Felt', 'Bradley Hand', cursive", 400, "normal"),
}
FALLBACK = "'Khmer Sangam MN', 'Khmer MN', 'Hiragino Sans GB', 'PingFang SC'"
PRICE = re.compile(r"[$¥￥€£៛]\s?\d|\d\s?(\$|usd|riel|៛|元)", re.I)
DATE = re.compile(r"\b\d{1,2}[:.]\d{2}\b|\b\d{1,2}\s?[-/.~]\s?\d{1,2}\b|\d{1,2}月|\b(mon|tue|wed|thu|fri|sat|sun|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", re.I)
ROLES = ["title", "subtitle", "label", "date", "price", "item-name", "description", "tag", "badge", "faded-word",
         "logo", "fine-print", "slogan"]

LABEL_PROMPT = """This poster has numbered red boxes around its text. For EVERY number, say what the text is for and what
lettering it uses. Reply with JSON only, like:
{"1": {"role": "title", "font": "serif-italic"}, "2": {"role": "price", "font": "serif-italic"}}
role: one of """ + ", ".join(ROLES) + """
font: one of """ + ", ".join(FONTS) + """
Look closely: serif letters have little feet; italic letters lean; script is joined-up handwriting; condensed is tall and narrow."""


def numbered(ref, blocks):
    """The reference with a numbered red box around each text block (for the vision model)."""
    img = ref.convert("RGB").copy()
    W, H = img.size
    k = 1100 / max(W, H)
    img = img.resize((int(W * k), int(H * k)))
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(_font_path(BOLD_FONT), 22) if _font_path(BOLD_FONT) else None
    for i, b in enumerate(blocks, 1):
        x0, y0, x1, y1 = (v * k for v in b["box"])
        d.rectangle((x0, y0, x1, y1), outline=(230, 20, 20), width=3)
        d.rectangle((x0, y0 - 24, x0 + 30, y0), fill=(230, 20, 20))
        d.text((x0 + 4, y0 - 24), str(i), font=f, fill=(255, 255, 255))
    return img


def background(ref):
    """Solid color or a top-to-bottom gradient, read from the left and right edges of the reference."""
    rgb = np.array(ref.convert("RGB"))
    h, w, _ = rgb.shape
    edge = np.concatenate([rgb[:, : max(2, w // 25)], rgb[:, -max(2, w // 25):]], axis=1)
    top = np.median(edge[: h // 6].reshape(-1, 3), axis=0)
    bottom = np.median(edge[-h // 6:].reshape(-1, 3), axis=0)
    hexc = lambda c: "#%02x%02x%02x" % tuple(int(v) for v in c)
    if np.linalg.norm(top - bottom) > 20:
        return f"linear-gradient(180deg, {hexc(top)} 0%, {hexc(bottom)} 100%)"
    return hexc((top + bottom) / 2)


def shape_css(s):
    """A box/badge behind text: rectangle, pill, circle or starburst, from how much of its box the shape fills."""
    m = np.array(s["mask"]) > 0
    fill = m.mean()
    w, h = s["mask"].size
    color = "#%02x%02x%02x" % s["color"]
    if fill > 0.9:
        return f"background:{color};border-radius:{int(min(w, h) * 0.08)}px;"
    if fill > 0.75 and abs(w - h) > min(w, h) * 0.3:
        return f"background:{color};border-radius:{int(min(w, h) / 2)}px;"
    if fill > 0.72:
        return f"background:{color};border-radius:50%;"
    pts = []   # spiky outline: a 12-point starburst
    for i in range(24):
        r = 50 if i % 2 == 0 else 36
        a = np.pi * 2 * i / 24 - np.pi / 2
        pts.append(f"{50 + r * np.cos(a):.1f}% {50 + r * np.sin(a):.1f}%")
    return f"background:{color};clip-path:polygon({','.join(pts)});"


def analyze_reference(ref, ask_vision=None):
    """Measurements plus the vision model's labels. ask_vision(prompt, image) -> text."""
    a = analyze(ref)
    labels = {}
    if ask_vision and a["blocks"]:
        try:
            m = re.search(r"\{.*\}", ask_vision(LABEL_PROMPT, numbered(a["ref"], a["blocks"])), re.S)
            labels = json.loads(m.group(0)) if m else {}
        except Exception:   # noqa: BLE001  (no vision model: guess from the measurements)
            labels = {}
    hs = sorted((b["h"] for b in a["blocks"]), reverse=True) or [1]
    for i, b in enumerate(a["blocks"], 1):
        got = labels.get(str(i)) or {}
        role = got.get("role") if got.get("role") in ROLES else None
        font = got.get("font") if got.get("font") in FONTS else None
        if b["faded"] and b["h"] < hs[0] * 0.3:   # small and light-colored: a pale price or note, not a background word
            b["faded"] = False
        if b["faded"]:
            role, font = "faded-word", font or "script"
        elif PRICE.search(b["text"]):   # rules beat the small vision model for these
            role = "price"
        elif DATE.search(b["text"]):
            role = "date"
        elif b["h"] >= hs[0] * 0.8:
            role = "title"
        b["role"] = role or ("title" if b["h"] >= hs[0] * 0.8 else "badge" if b["boxed"] else "description")
        b["font"] = font or ("sans-black" if b["heavy"] and b["h"] >= hs[0] * 0.8 else "sans-bold" if b["heavy"] else "sans")
    a["background"] = background(a["ref"])
    return a


def describe(a):
    """The blocks as the copywriter (chat model) sees them."""
    W, H = a["size"]
    out = []
    for b in a["blocks"]:
        cx, cy = (b["box"][0] + b["box"][2]) / 2 / W, (b["box"][1] + b["box"][3]) / 2 / H
        where = ("top" if cy < 0.33 else "bottom" if cy > 0.66 else "middle") + "-" + ("left" if cx < 0.4 else "right" if cx > 0.6 else "center")
        out.append(f'{b["id"]}: {b["role"]}, {where}, old text "{b["text"]}" ({len(b["text"])} characters)')
    return "\n".join(out)


def _units(s):
    """Visual width in Latin-letter units: a Chinese / Khmer character is about two letters wide."""
    return sum(2 if ("\u3000" <= c <= "\u9fff" or "\uff00" <= c <= "\uffef" or "\u1780" <= c <= "\u17ff") else 1 for c in s)


def _layout(a, texts):
    """Where each new text goes (in reference pixels): [(block, text, left, top, width, height, align, wrap)]."""
    W, _ = a["size"]
    out = []
    for b in a["blocks"]:
        t = texts.get(b["id"], "")
        if not t:
            continue
        x0, y0, x1, y1 = b["box"]
        cx = (x0 + x1) / 2 / W
        align = "center" if b["boxed"] or b["role"] in ("badge", "faded-word") or 0.42 < cx < 0.58 else ("right" if cx > 0.6 else "left")
        longer = _units(t) > _units(b["text"]) * 1.5
        wrap = b["role"] in ("item-name", "slogan") and longer
        room = (x1 - x0) * (1.0 if b["boxed"] else 1.6 if b["role"] in ("title", "faded-word", "subtitle") else 1.4)
        if wrap:
            room = max(room, (x1 - x0) * 2.2, b["h"] * 7)
        room = min(room, W * 0.92)   # text never runs off the poster
        left = {"left": x0, "center": (x0 + x1) / 2 - room / 2, "right": x1 - room}[align]
        left = min(max(left, W * 0.04), W * 0.96 - room)
        height = (y1 - y0) * (2.3 if wrap else 1.0)
        out.append((b, t, left, y0, room, height, align, wrap))
    return out


def place_product(a, texts, product_size):
    """The biggest spot inside the reference's product area that doesn't cover any text. Returns (x, y, w, h)."""
    ux0, uy0, ux1, uy1 = a["product"]
    pw, ph = product_size
    rects = []
    for b, t, l, top, w, h, align, wrap in _layout(a, texts):
        if b["role"] == "faded-word":
            continue
        tw = min(w, _units(t) * b["h"] * 0.62 / (2 if wrap else 1))   # roughly how wide the words really are
        x = {"left": l, "center": l + (w - tw) / 2, "right": l + w - tw}[align]
        rects.append((x - 10, top - 8, x + tw + 10, top + h + 8))
    best = None
    for scale in (1.0, 0.92, 0.85, 0.78, 0.72, 0.66, 0.6, 0.55, 0.5, 0.45):
        r = min((ux1 - ux0) * scale / pw, (uy1 - uy0) * scale / ph)
        w, h = pw * r, ph * r
        for y in (uy1 - h, (uy0 + uy1 - h) / 2):
            for x in ((ux0 + ux1 - w) / 2, ux0 + (ux1 - ux0 - w) * 0.35, ux0 + (ux1 - ux0 - w) * 0.65, ux0, ux1 - w):
                hit = sum(max(0, min(x + w, R[2]) - max(x, R[0])) * max(0, min(y + h, R[3]) - max(y, R[1])) for R in rects)
                if hit < 0.02 * w * h:
                    return (x, y, w, h)
                if best is None:
                    best = (x, y, w, h)
    return (best[0] + best[2] * 0.25, best[1] + best[3] * 0.5, best[2] * 0.5, best[3] * 0.5)


def build_html(a, texts, product_file=None, width=1080, title="FongAI design", product_size=None):
    """texts: {block id: new text}. product_file: the cut-out PNG's file name (next to the HTML); product_size its (w, h)."""
    W, H = a["size"]
    k = width / W
    height = round(H * k)
    px = lambda v: f"{v * k:.1f}px"
    parts = []
    for s in a["shapes"]:
        x0, y0, x1, y1 = s["box"]
        parts.append(f'<div class="shape" style="left:{px(x0)};top:{px(y0)};width:{px(x1 - x0)};height:{px(y1 - y0)};{shape_css(s)}"></div>')
    if product_file and a["product"]:
        x, y, w, h = place_product(a, texts, product_size or (a["product"][2] - a["product"][0], a["product"][3] - a["product"][1]))
        parts.append(f'<img class="product" src="{html.escape(product_file)}" style="left:{px(x)};top:{px(y)};width:{px(w)};height:{px(h)}">')
    for b, t, left, top, room, _, align, wrap in _layout(a, texts):
        family, weight, style = FONTS.get(b["font"], FONTS["sans"])
        x0, y0, x1, y1 = b["box"]
        color = "#%02x%02x%02x" % b["ink"]
        size = b["h"] * k * (1.18 if b["font"] in ("script", "handwritten") else 1.05)
        extra = ""   # a faded word's color is already pale
        anchor = f"top:{px(y0)};translate:none;" if wrap else f"top:{px((y0 + y1) / 2)};"   # wrapped text grows downward
        rot = f"transform:rotate({-b['angle']:.1f}deg);" if abs(b["angle"]) > 3 else ""
        parts.append(
            f'<div class="t{" wrap" if wrap else ""}" contenteditable="true" data-role="{b["role"]}" style="left:{px(left)};{anchor}'
            f'width:{px(room)};font-family:{family},{FALLBACK};font-weight:{weight};font-style:{style};font-size:{size:.1f}px;'
            f'color:{color};text-align:{align};{extra}{rot}">{html.escape(t)}</div>')
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>
  html, body {{ margin: 0; padding: 0; }}
  body {{ display: flex; justify-content: center; background: #f2f2f2; }}
  .poster {{ position: relative; width: {width}px; height: {height}px; overflow: hidden; background: {a["background"]}; }}
  .shape, .product, .t {{ position: absolute; }}
  .product {{ object-fit: contain; object-position: center bottom; }}
  .t {{ white-space: nowrap; line-height: 1; transform-origin: center; translate: 0 -50%; outline: none; }}
  .t.wrap {{ white-space: normal; line-height: 1.12; }}   /* longer new words: two lines instead of tiny letters */
  .t:focus {{ outline: 2px dashed rgba(60, 120, 255, .7); outline-offset: 4px; }}
  @media print {{ body {{ background: none; }} }}
</style></head>
<body><div class="poster">
{chr(10).join(parts)}
</div>
<script>
  // shrink any text that's wider than its space (new words can be longer than the old ones)
  document.querySelectorAll('.t').forEach(el => {{
    let s = parseFloat(el.style.fontSize);
    const tooBig = () => el.scrollWidth > el.clientWidth + 1 || (el.classList.contains('wrap') && el.scrollHeight > s * 2.4);
    while (tooBig() && s > 8) {{ s *= 0.94; el.style.fontSize = s + 'px'; }}
  }});
</script>
</body></html>"""


def render_png(html_path, png_path, width, height):
    """Chrome draws the HTML page to a PNG of exactly width x height."""
    if not os.path.exists(CHROME):
        raise RuntimeError("Designs need Google Chrome (set CHROME_BIN to its path).")
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                    "--force-device-scale-factor=1", f"--window-size={width},{height}", "--virtual-time-budget=3000",
                    f"--screenshot={png_path}", "file://" + html_path], check=True, timeout=120,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not os.path.exists(png_path):
        raise RuntimeError("Chrome didn't produce the picture.")
    return Image.open(png_path)
