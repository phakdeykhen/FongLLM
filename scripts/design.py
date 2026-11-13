"""
Designed graphics in any size: banners, posters, social posts, stories, standees, thumbnails, step-and-repeat walls.
The chat model plans the words, the image model paints only the photo (it can't spell), and every word is typeset
here in a real font, so text is always sharp and spelled right. Sizes and layouts come from design_catalog.py.

Layouts (see design_catalog.py): banner, thumb, square, poster, tall, repeat.

  python scripts/design.py plan.json --layout poster --size 1697x2400 --hero photo.png -o out.png
"""
import re

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import design_style

from promo_poster import _font, _wrap, cover, mix

WHITE, SOFT, CTA_BG, CTA_FG = (255, 255, 255), (206, 216, 238), (255, 184, 28), (24, 24, 40)

# Words that make the image model paint lettering (it can't spell: you get fake text like "BAREB")
WORDY = re.compile(r"\b(banners?|posters?|signs?|signboards?|billboards?|flyers?|texts?|words?|letters?|logos?|titles?|"
                   r"headlines?|captions?|labels?|brand names?|typography|slogans?|ads?|advert\w*|prompts?|briefs?|"
                   r"generators?|templates?|mock-?ups?|thumbnails?|covers?|backdrops?|standees?|flags?)\b", re.I)
PLACE = {
    "banner": "placed on the right side of the frame, empty dark background on the left side",
    "thumb": "close-up, expressive, placed on the right side of the frame, bold dramatic lighting, empty left side",
    "square": "centered in the upper part of the frame, clean background",
    "poster": "centered in the upper part of the frame, clean background",
    "tall": "centered, full figure, clean background",
}


def hex_color(s, default=(37, 99, 235)):
    m = re.fullmatch(r"#?([0-9a-f]{6})", str(s or "").strip(), re.I)
    return tuple(int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4)) if m else default


def hero_prompt(subject, layout="banner"):
    """What the image model paints: the picture only, placed where the layout leaves room for it."""
    if WORDY.search(subject) or not subject.strip():   # a picture of lettering: paint a person instead
        subject = "a smiling young professional working on a laptop in a modern bright office"
    return (f"{subject}, {PLACE.get(layout, PLACE['poster'])}, professional advertising photography, cinematic "
            "lighting, sharp focus, high detail, no text, no letters, no words, no logo, no watermark")


def _gradient(size, accent, horizontal=True):
    w, h = size
    deep, mid = mix(accent, (4, 8, 24), 0.82), mix(accent, (4, 8, 24), 0.45)
    x = np.linspace(0, 1, w)[None, :, None]
    y = np.linspace(0, 1, h)[:, None, None]
    t = np.clip(0.75 * x + 0.25 * y, 0, 1) if horizontal else np.clip(0.25 * x + 0.75 * y, 0, 1)
    arr = np.array(deep) * (1 - t) + np.array(mid) * t
    return Image.fromarray(np.broadcast_to(arr, (h, w, 3)).astype(np.uint8))


def _fade_mask(size, axis, start, end, power=1.4):
    """0 -> 255 ramp along x (axis 1) or y (axis 0) between fractions start and end."""
    w, h = size
    n = w if axis == 1 else h
    ramp = (np.clip((np.linspace(0, 1, n) - start) / max(end - start, 1e-6), 0, 1) ** power * 255).astype(np.uint8)
    arr = np.broadcast_to(ramp[None, :], (h, w)) if axis == 1 else np.broadcast_to(ramp[:, None], (h, w))
    return Image.fromarray(np.ascontiguousarray(arr))


def _pill(d, xy, text, f, fill, color, pad):
    l, t, r, b = d.textbbox((0, 0), text, font=f)
    w, h = r - l + pad[0] * 2, f.size + pad[1] * 2
    if xy is None:
        return w, h
    x, y = xy
    d.rounded_rectangle((x, y, x + w, y + h), radius=h // 2, fill=fill)
    d.text((x + pad[0] - l, y + (h - (b - t)) / 2 - t), text, font=f, fill=color)
    return w, h


def _brand(d, x, y, brand, accent, u, color=WHITE):
    if not brand:
        return
    s = int(58 * u)
    bright = mix(accent, WHITE, 0.45)
    d.rounded_rectangle((x, y, x + s, y + s), radius=int(14 * u), fill=bright)
    f = _font(brand[0], True, int(36 * u))
    l, t, r, b = d.textbbox((0, 0), brand[0].upper(), font=f)
    d.text((x + s / 2 - (r - l) / 2 - l, y + s / 2 - (b - t) / 2 - t), brand[0].upper(), font=f, fill=mix(accent, (0, 0, 0), 0.6))
    fb = _font(brand, False, int(40 * u))
    d.text((x + s + 18 * u, y + 6 * u), brand, font=fb, fill=color)


def _headline_lines(text, highlight, size, max_w, max_lines):
    f, lines = _wrap(text, True, size, max_w, max_lines)
    marked = set(w.lower().strip(",.!?") for w in (highlight or "").split())
    return f, lines, marked


def _draw_headline(d, x, y, f, lines, marked, accent, center_w=None, stroke=0):
    """Returns the y where the drawn letters really end (heavy fonts reach well below their nominal line height)."""
    space = f.getlength(" ")
    bottom = y
    for line in lines:
        cx = x + (center_w - f.getlength(line)) / 2 if center_w else x
        for word in line.split():
            fill = accent if word.lower().strip(",.!?") in marked else WHITE
            d.text((cx, y), word, font=f, fill=fill, stroke_width=stroke, stroke_fill=(0, 0, 0))
            bottom = max(bottom, y + d.textbbox((0, 0), word, font=f, stroke_width=stroke)[3])
            cx += f.getlength(word) + space
        y += f.size * 1.08
    return bottom


def _chips(img, feats, u, x0, y, max_w, accent, center=False):
    """Frosted rounded pills with a drawn check mark; wraps onto a second row. Returns (img, bottom y)."""
    f = _font(" ".join(feats), False, int(24 * u))
    h, gap = int(54 * u), int(14 * u)
    rows, row, row_w = [], [], 0
    for ft in feats:
        w = f.getlength(ft) + 78 * u
        if row and row_w + gap + w > max_w:
            rows.append((row, row_w))
            row, row_w = [], 0
        row.append((ft, w))
        row_w += (gap if row_w else 0) + w
    if row:
        rows.append((row, row_w))
    rows = rows[:2]
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    spots = []
    for i, (row, row_w) in enumerate(rows):
        x = x0 + (max_w - row_w) / 2 if center else x0
        yy = y + i * (h + gap)
        for ft, w in row:
            ld.rounded_rectangle((x, yy, x + w, yy + h), radius=h // 2, fill=(255, 255, 255, 30), outline=(255, 255, 255, 80), width=2)
            spots.append((x, yy, ft))
            x += w + gap
    img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")
    d = ImageDraw.Draw(img)
    bright = mix(accent, WHITE, 0.45)
    for x, yy, ft in spots:
        cx, cy = x + 30 * u, yy + h / 2
        d.line([(cx - 9 * u, cy), (cx - 3 * u, cy + 7 * u), (cx + 10 * u, cy - 8 * u)], fill=bright, width=max(2, int(4 * u)), joint="curve")
        l, t, r, b = d.textbbox((0, 0), ft, font=f)
        d.text((x + 52 * u - l, yy + (h - (b - t)) / 2 - t), ft, font=f, fill=WHITE)
    return img, y + len(rows) * (h + gap)


def _text_of(plan):
    return lambda k: str(plan.get(k) or "").strip()


def _features(plan):
    return [str(x).strip() for x in plan.get("features") or [] if str(x).strip()][:4]


# ---------- wide: text left, photo right ----------
def _landscape(plan, hero, size, thumb=False):
    W, H = size
    u = min(H / 900, W / 1600)
    text = _text_of(plan)
    accent = hex_color(plan.get("color"))
    bright = mix(accent, WHITE, 0.45)
    img = _gradient(size, accent)
    if hero is not None:
        pw = int(W * (0.6 if thumb else 0.62))
        img.paste(cover(hero, (pw, H)), (W - pw, 0), _fade_mask((pw, H), 1, -0.1, 0.55 if thumb else 0.9))
    d = ImageDraw.Draw(img)
    left, col = int(84 * u), int(W * (0.56 if thumb else 0.5)) - int(84 * u)

    if thumb:   # few huge words with a black outline: readable at phone size
        f, lines, marked = _headline_lines(text("headline") or text("brand"), text("highlight"), int(170 * u), col, 3)
        total = len(lines) * f.size * 1.08
        _draw_headline(d, left, (H - total) / 2, f, lines, marked, CTA_BG, stroke=max(3, int(8 * u)))
        _brand(d, left, int(40 * u), text("brand"), accent, u * 0.8)
        return img

    y = int(64 * u)
    _brand(d, left, y, text("brand"), accent, u)
    y += int(110 * u) if text("brand") else 0
    if text("eyebrow"):
        f = _font(text("eyebrow"), False, int(26 * u))
        _, h = _pill(d, (left, y), text("eyebrow"), f, accent, WHITE, (int(22 * u), int(10 * u)))
        y += h + int(26 * u)
    f, lines, marked = _headline_lines(text("headline") or text("brand") or "Your headline", text("highlight"), int(80 * u), col, 3)
    y = _draw_headline(d, left, y, f, lines, marked, bright) + int(30 * u)
    room = H - y - int(96 * u if _features(plan) else 40 * u)
    if text("subheadline") and room > 160 * u:
        f, lines = _wrap(text("subheadline"), False, int(31 * u), col - int(40 * u), 3)
        for line in lines:
            d.text((left, y), line, font=f, fill=SOFT)
            y += f.size * 1.32
        y += int(30 * u)
    if text("cta") and H - y > 170 * u:
        _pill(d, (left, y), text("cta") + "  →", _font(text("cta"), True, int(32 * u)), CTA_BG, CTA_FG, (int(38 * u), int(20 * u)))
    if _features(plan):
        img, _ = _chips(img, _features(plan), u, left, H - int(96 * u), W - left - int(40 * u), accent)
    return img


# ---------- square / portrait / tall: photo on top, text below ----------
def _vertical(plan, hero, size, layout):
    W, H = size
    u = W / 1080
    text = _text_of(plan)
    accent = hex_color(plan.get("color"))
    bright = mix(accent, WHITE, 0.45)
    img = _gradient(size, accent, horizontal=False)
    photo_h = int(H * {"square": 0.52, "poster": 0.56, "tall": 0.5}[layout])
    top = int(H * 0.08) if layout == "tall" else 0   # standees: brand band above the photo
    if hero is not None:
        img.paste(cover(hero, (W, photo_h)), (0, top), Image.eval(_fade_mask((W, photo_h), 0, 0.55, 1.0, 1.2), lambda v: 255 - v))
    scrim = Image.new("RGB", (W, int(170 * u)), mix(accent, (0, 0, 0), 0.85))   # keeps the brand readable over the photo
    img.paste(scrim, (0, 0), Image.eval(_fade_mask((W, int(170 * u)), 0, 0, 1), lambda v: int((255 - v) * 0.7)))
    margin = int(70 * u)
    col = W - 2 * margin
    _brand(ImageDraw.Draw(img), margin, int(48 * u), text("brand"), accent, u)

    # The text block must fit between the photo and the bottom edge. Keep the headline big: first leave out the
    # least important parts (feature chips, then the description), and only then make everything smaller.
    tries = [(1.0, ()), (1.0, ("features",)), (0.9, ("features",)), (1.0, ("features", "subheadline")),
             (0.85, ("features", "subheadline")), (0.75, ("features", "subheadline")), (0.65, ("features", "subheadline", "eyebrow")),
             (0.55, ("features", "subheadline", "eyebrow"))]
    def draw(k, drop, y):
        trial = img.copy()
        d = ImageDraw.Draw(trial)
        if text("eyebrow") and "eyebrow" not in drop:
            f = _font(text("eyebrow"), False, int(30 * u * k))
            w, h = _pill(d, None, text("eyebrow"), f, accent, WHITE, (int(24 * u), int(11 * u)))
            _pill(d, ((W - w) / 2, y), text("eyebrow"), f, accent, WHITE, (int(24 * u), int(11 * u)))
            y += h + int(28 * u * k)
        f, lines, marked = _headline_lines(text("headline") or text("brand") or "Your headline", text("highlight"), int(112 * u * k), col, 3)
        y = _draw_headline(d, margin, y, f, lines, marked, bright, center_w=col) + int(30 * u * k)
        if text("subheadline") and "subheadline" not in drop:
            f, lines = _wrap(text("subheadline"), False, int(38 * u * k), col - int(40 * u), 3)
            for line in lines:
                d.text((margin + (col - f.getlength(line)) / 2, y), line, font=f, fill=SOFT)
                y += f.size * 1.3
            y += int(34 * u * k)
        if text("cta"):
            f = _font(text("cta"), True, int(40 * u * k))
            label = text("cta") + "  →"
            w, h = _pill(d, None, label, f, CTA_BG, CTA_FG, (int(44 * u * k), int(22 * u * k)))
            _pill(d, ((W - w) / 2, y), label, f, CTA_BG, CTA_FG, (int(44 * u * k), int(22 * u * k)))
            y += h + int(34 * u * k)
        if _features(plan) and "features" not in drop:
            trial, y = _chips(trial, _features(plan), u * k, margin, y, col, accent, center=True)
        return trial, y

    start, bottom = top + photo_h - int(40 * u), H - int(50 * u)
    for k, drop in tries:
        trial, end = draw(k, drop, start)
        if end <= bottom:
            spare = bottom - end   # sit the block in the middle of the space under the photo
            return draw(k, drop, start + spare // 2)[0] if spare > 20 * u else trial
    return trial


# ---------- step and repeat: the brand tiled across the wall ----------
def _repeat(plan, size):
    W, H = size
    u = H / 1600
    text = _text_of(plan)
    accent = hex_color(plan.get("color"))
    img = Image.new("RGB", size, mix(accent, (255, 255, 255), 0.92))
    d = ImageDraw.Draw(img)
    names = [n for n in (text("brand"), text("eyebrow") or text("headline")) if n][:2] or ["Your Brand"]
    f = _font(" ".join(names), True, int(64 * u))
    cell_w = max(f.getlength(n) for n in names) + 160 * u
    cell_h = 230 * u
    colors = [mix(accent, (0, 0, 0), 0.25), mix(accent, (0, 0, 0), 0.55)]
    row = 0
    y = 50 * u
    while y < H:
        x = -cell_w / 2 if row % 2 else 40 * u
        i = row
        while x < W:
            n = names[i % len(names)]
            d.text((x + (cell_w - f.getlength(n)) / 2, y), n, font=f, fill=colors[i % 2])
            x += cell_w
            i += 1
        y += cell_h
        row += 1
    return img


# ---------- styled: follow a reference design ("like image 2") ----------
def _sfont(text, path, size):
    """The style's font, but Khmer / Chinese text needs a font that has those letters."""
    if path is None or any("\u1780" <= c <= "\u17ff" or "\u3000" <= c <= "\u9fff" for c in text):
        return _font(text, True, size)
    file, index = path if isinstance(path, tuple) else (path, 0)
    return ImageFont.truetype(file, size, index=index)


def _fit_lines(text, path, size, max_w, max_lines):
    words = text.split()
    while size > 20:
        f = _sfont(text, path, size)
        lines, cur = [], ""
        for wd in words:
            t = f"{cur} {wd}".strip()
            if f.getlength(t) <= max_w or not cur:
                cur = t
            else:
                lines.append(cur)
                cur = wd
        lines.append(cur)
        if len(lines) <= max_lines and all(f.getlength(l) <= max_w for l in lines):
            return f, lines
        size -= 4
    return _sfont(text, path, size), [text]


def _paste_rotated(img, layer, xy, angle):
    """Paste an RGBA layer (text or product) at xy (its center), rotated by angle degrees."""
    if angle:
        layer = layer.rotate(angle, resample=Image.BICUBIC, expand=True)
    x, y = int(xy[0] - layer.width / 2), int(xy[1] - layer.height / 2)
    img.paste(layer, (x, y), layer)


def _text_layer(lines, f, color, align="center", spacing=1.02):
    w = int(max(f.getlength(l) for l in lines)) + 20
    tops = [f.getbbox(l)[1] for l in lines]
    h = int(f.size * spacing * len(lines) + f.size * 0.4)
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    y = 0
    for line, top in zip(lines, tops):
        x = (w - f.getlength(line)) / 2 if align == "center" else 10
        d.text((x, y - top * 0.5), line, font=f, fill=color)
        y += f.size * spacing
    return layer.crop(layer.getbbox() or (0, 0, w, h))


def _main_shapes(product):
    """Drop small separate bits from a cut-out (a logo printed above the product, specks), keep the product itself."""
    import cv2
    a = np.array(product.getchannel("A"))
    n, labels, stats, _ = cv2.connectedComponentsWithStats((a > 40).astype(np.uint8), 8)
    if n <= 2:
        return product
    biggest = stats[1:, cv2.CC_STAT_AREA].max()
    keep = np.isin(labels, [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= biggest * 0.08])
    out = np.array(product)
    out[..., 3] = np.where(keep, out[..., 3], 0)
    img = Image.fromarray(out)
    return img.crop(img.getbbox() or (0, 0, *img.size))


def _styled(plan, product, style, size):
    """product: RGBA cut-out (or None). style: from design_style.read_style."""
    W, H = size
    u = W / 1080
    text = _text_of(plan)
    bg, ink, accent = style["bg"], style["text"], style["accent"]
    img = Image.new("RGB", size, bg)
    grain = np.random.default_rng(7).normal(0, 6, (H, W, 1))   # a little paper grain, like printed posters
    img = Image.fromarray(np.clip(np.array(img, np.float32) + grain, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img)
    small = design_style.first_font(design_style.SMALL_FONT)
    head_path = design_style.font_file(style["lettering"])
    playful = style.get("playful")
    top_text = style.get("text_position") == "top"
    margin = int(64 * u)

    # top: a small uppercase label on the left, details on the right (like event posters)
    y_top = int(56 * u)
    if text("eyebrow"):
        f = _sfont(text("eyebrow"), small, int(44 * u))
        d.text((margin, y_top), text("eyebrow").upper(), font=f, fill=ink)
    if text("subheadline"):
        f, lines = _fit_lines(text("subheadline"), small, int(30 * u), int(W * 0.42), 3)
        y = y_top
        for line in lines:
            d.text((W - margin - f.getlength(line), y), line, font=f, fill=ink)
            y += f.size * 1.15

    # the headline: big, in the reference's lettering and accent color
    head = text("headline") or text("brand") or "Your headline"
    f, lines = _fit_lines(head, head_path, int(230 * u), W - 2 * margin, 2)
    layer = _text_layer(lines, f, accent)
    head_cy = int(H * 0.30) if top_text else int(H * 0.80)

    # the product: as big as the space allows, with a soft shadow; tilted when the reference is playful
    word = text("highlight") or ""
    show_word = bool(word) and len(word) <= 18 and word.lower() not in head.lower()
    word_room = int(70 * u * 0.9) if show_word and not top_text else 0   # the script word sits between product and headline
    if product is not None:
        product = _main_shapes(product.convert("RGBA"))
        gap = int(30 * u) + word_room
        if top_text:
            box_top = head_cy + layer.height // 2 + gap
            box_h = H - int(130 * u) - box_top
        else:
            box_top = int(H * 0.13)
            box_h = head_cy - layer.height // 2 - gap - box_top
        k = min(W * 0.78 / product.width, box_h / product.height)
        prod = product.resize((max(1, int(product.width * k)), max(1, int(product.height * k))), Image.LANCZOS)
        angle = -8 if playful else 0
        cx, cy = W // 2, box_top + box_h // 2
        shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        sw, sh = prod.width * 0.42, prod.height * 0.06
        ImageDraw.Draw(shadow).ellipse((cx - sw, cy + prod.height * 0.47 - sh, cx + sw, cy + prod.height * 0.47 + sh),
                                       fill=(0, 0, 0, 70))
        img.paste(shadow.filter(ImageFilter.GaussianBlur(18 * u)), (0, 0), shadow.filter(ImageFilter.GaussianBlur(18 * u)))
        _paste_rotated(img, prod, (cx, cy), angle)

    _paste_rotated(img, layer, (W // 2, head_cy), 4 if playful else 0)
    d = ImageDraw.Draw(img)

    # a small script word next to the headline ("relax", "new!", the key benefit)
    if show_word:
        sf = _sfont(word, design_style.first_font(design_style.ACCENT_SCRIPT), int(70 * u))
        wl = _text_layer([word], sf, ink)
        hx = min(W - margin - wl.width / 2, W / 2 + layer.width / 2 - wl.width * 0.2)   # over the headline's right end
        _paste_rotated(img, wl, (hx, head_cy - layer.height / 2 - wl.height * 0.75), -10 if playful else 0)

    # bottom line: brand on the left, call to action on the right
    d = ImageDraw.Draw(img)
    f = _sfont(text("brand") or "", small, int(40 * u))
    yb = H - int(70 * u)
    if text("brand"):
        d.text((margin, yb), text("brand").upper(), font=f, fill=ink)
    if text("cta"):
        cf = _sfont(text("cta"), small, int(36 * u))
        label = text("cta").upper()   # condensed poster fonts have no arrow glyph
        w, h = _pill(d, None, label, cf, accent, bg, (int(26 * u), int(12 * u)))
        _pill(d, (W - margin - w, yb - int(10 * u)), label, cf, accent, bg, (int(26 * u), int(12 * u)))
    return img


def make_design(plan, hero=None, layout="banner", size=(1600, 900), style=None):
    """plan: {brand, eyebrow, headline, highlight, subheadline, features: [..], cta, color}. hero: PIL image or None.
    style: from design_style.read_style (follow a reference design); hero is then the RGBA product cut-out."""
    if style is not None:
        return _styled(plan, hero, style, size)
    if layout == "repeat":
        return _repeat(plan, size)
    if layout in ("banner", "thumb"):
        return _landscape(plan, hero, size, thumb=layout == "thumb")
    return _vertical(plan, hero, size, layout if layout in ("square", "poster", "tall") else "poster")


if __name__ == "__main__":
    import argparse
    import json
    p = argparse.ArgumentParser()
    p.add_argument("plan")
    p.add_argument("--layout", default="banner")
    p.add_argument("--size", default="1600x900")
    p.add_argument("--hero")
    p.add_argument("-o", default="design.png")
    a = p.parse_args()
    size = tuple(int(v) for v in a.size.split("x"))
    make_design(json.load(open(a.plan)), Image.open(a.hero) if a.hero else None, a.layout, size).save(a.o)
    print(a.o)
