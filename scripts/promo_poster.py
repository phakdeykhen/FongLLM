"""
Promotion poster from a real product photo. The product is cut out of the user's own photo (never redrawn, so
bottles, labels and logos stay exactly right) and every word is typeset in a real font (the image model can't spell).
The image model only paints the empty backdrop behind it; without it a soft gradient is used.

  python scripts/promo_poster.py product.jpg --title "ANUA Skincare Set" --price '$10' -o poster.png
"""
import os
import re

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from poster_text import BOLD_FONT, CJK_FONT, HEAVY_FONT, KHMER_FONT, _font_path

W, H = 1080, 1350   # 4:5, the shape Facebook / Instagram feeds show biggest
PRICE = re.compile(r"(?:\$|usd\s?)\s?\d+(?:[.,]\d+)?|\d+(?:[.,]\d+)?\s?(?:\$|usd\b|dollars?\b|riels?\b|៛|元|¥|€|£)", re.I)


def find_price(text):
    """'a set 10$only' -> '$10'; '$9.99' stays; '20000 riel' -> '20000៛'."""
    m = PRICE.search(text or "")
    if not m:
        return ""
    s = m.group(0).strip()
    num = re.search(r"\d+(?:[.,]\d+)?", s).group(0)
    if "$" in s or re.search(r"usd|dollar", s, re.I):
        return f"${num}"
    if re.search(r"riel|៛", s, re.I):
        return f"{num}៛"
    return s.replace(" ", "")


# ---------- product cut-out ----------
CUTOUT_MODEL = os.environ.get("POSTER_CUTOUT_MODEL", "birefnet-general-lite")   # rembg model; ~220MB, downloaded once


def ai_cutout(photo):
    """AI background removal (rembg + BiRefNet): clean soft edges, keeps a white lid on a white background, drops
    stray text around the product. None if rembg isn't installed or nothing sensible was found."""
    try:
        from rembg import new_session, remove
    except ImportError:
        return None
    rgb = photo.convert("RGB")
    if max(rgb.size) < 1200:   # small photos: enlarge first so the edge stays smooth on a 1080px poster
        k = 1200 / max(rgb.size)
        rgb = rgb.resize((round(rgb.width * k), round(rgb.height * k)), Image.LANCZOS)
    try:
        session = new_session(CUTOUT_MODEL)   # not cached: frees its ~2GB right after (16GB Macs)
        alpha = np.array(remove(rgb, session=session, only_mask=True, post_process_mask=False).convert("L"))
    except Exception:   # noqa: BLE001  (model download failed, etc.)
        return None
    cover = (alpha > 128).mean()
    if cover < 0.03 or cover > 0.92:
        return None
    # keep the product, drop small specks (bits of text or shadow the model half-kept)
    n, labels, stats, _ = cv2.connectedComponentsWithStats((alpha > 128).astype(np.uint8), 8)
    if n > 2:
        big = stats[1:, cv2.CC_STAT_AREA].max()
        keep = np.isin(labels, [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= 0.02 * big])
        keep = cv2.dilate(keep.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
        alpha = np.where(keep, alpha, 0).astype(np.uint8)
    ys, xs = np.nonzero(alpha > 20)
    out = np.dstack([np.array(rgb), alpha])[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return Image.fromarray(out)


def cutout(photo):
    """RGBA product with a plain background removed, cropped to the product. None when the background isn't plain
    (a busy photo), so the caller shows the photo on a card instead."""
    rgb = np.array(photo.convert("RGB"))
    h, w = rgb.shape[:2]
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]]).astype(float)
    bg = np.median(border, axis=0)
    if np.mean(np.linalg.norm(border - bg, axis=1) < 30) < 0.8:
        return None
    near = (np.linalg.norm(rgb.astype(float) - bg, axis=2) < 22).astype(np.uint8)
    # background = the near-background areas touching the edge (a white bottle in the middle is kept)
    n, labels = cv2.connectedComponents(near, connectivity=4)
    edge = set(np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))) - {0}
    alpha = np.where(np.isin(labels, list(edge)) & (near > 0), 0, 255).astype(np.uint8)
    alpha = cv2.morphologyEx(alpha, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    if alpha.mean() / 255 < 0.03:
        return None
    alpha = cv2.GaussianBlur(alpha, (3, 3), 0)
    ys, xs = np.nonzero(alpha > 20)
    out = np.dstack([rgb, alpha])[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return Image.fromarray(out)


def card(photo):
    """Busy photo: rounded white card with the photo inside."""
    photo = photo.convert("RGB")
    pad, r = 18, 36
    c = Image.new("RGBA", (photo.width + 2 * pad, photo.height + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(c).rounded_rectangle([0, 0, c.width - 1, c.height - 1], r, fill=(255, 255, 255, 255))
    m = Image.new("L", photo.size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, photo.width - 1, photo.height - 1], r - pad // 2, fill=255)
    c.paste(photo, (pad, pad), m)
    return c


# ---------- colours ----------
def accent_color(product):
    """The product's main colourful tone (e.g. ANUA green); coral when the product is all white/grey."""
    arr = np.array(product.convert("RGBA")).reshape(-1, 4)
    arr = arr[arr[:, 3] > 200][:, :3]
    if len(arr):
        hsv = cv2.cvtColor(arr.reshape(-1, 1, 3).astype(np.uint8), cv2.COLOR_RGB2HSV).reshape(-1, 3)
        vivid = arr[(hsv[:, 1] > 70) & (hsv[:, 2] > 60)].astype(np.float32)
        if len(vivid) > 200:
            _, labels, centers = cv2.kmeans(vivid, 3, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0),
                                            3, cv2.KMEANS_PP_CENTERS)
            c = centers[np.bincount(labels.ravel(), minlength=3).argmax()]
            hsv_c = cv2.cvtColor(np.uint8([[c]]), cv2.COLOR_RGB2HSV)[0, 0]
            hsv_c[1] = max(hsv_c[1], 150)          # punchy, not muddy
            hsv_c[2] = min(max(hsv_c[2], 120), 190)  # dark enough for white text on it
            return tuple(int(v) for v in cv2.cvtColor(np.uint8([[hsv_c]]), cv2.COLOR_HSV2RGB)[0, 0])
    return (226, 78, 88)


def backdrop_prompt(photo):
    """Abstract backdrop in the product's colour. Turbo models ignore "no bottles", so never name objects at all."""
    product = cutout(photo) or photo
    r, g, b = accent_color(product)
    hue = cv2.cvtColor(np.uint8([[[r, g, b]]]), cv2.COLOR_RGB2HSV)[0, 0, 0] * 2
    name = next(n for h, n in ((15, "coral pink"), (40, "peach"), (70, "warm cream"), (165, "sage green and mint"),
                               (200, "aqua"), (260, "sky blue"), (300, "lavender"), (345, "blush pink"), (361, "coral pink"))
                if hue < h)
    return f"soft {name} gradient, abstract smooth silk fabric waves, gentle bokeh light, pastel, minimal, clean, airy"


def mix(a, b, t):
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def gradient_bg(accent):
    top, bottom = mix(accent, (255, 255, 255), 0.88), mix(accent, (255, 255, 255), 0.55)
    g = np.linspace(0, 1, H)[:, None, None]
    arr = (np.array(top) * (1 - g) + np.array(bottom) * g) * np.ones((H, W, 1))
    return Image.fromarray(arr.astype(np.uint8))


def cover(img, size=(W, H)):
    img = img.convert("RGB")
    k = max(size[0] / img.width, size[1] / img.height)
    img = img.resize((round(img.width * k), round(img.height * k)), Image.LANCZOS)
    x, y = (img.width - size[0]) // 2, (img.height - size[1]) // 2
    return img.crop((x, y, x + size[0], y + size[1]))


# ---------- text ----------
def _font(text, heavy, size):
    if any("ក" <= c <= "៿" for c in text):
        path = _font_path(KHMER_FONT)
    elif any("　" <= c <= "鿿" for c in text):
        path = _font_path(CJK_FONT)
    else:
        path = _font_path(HEAVY_FONT if heavy else BOLD_FONT) or _font_path(BOLD_FONT)
    return ImageFont.truetype(path, size) if path else ImageFont.load_default()


def _wrap(text, heavy, size, max_w, max_lines):
    """Biggest font size (down from `size`) at which `text` fits in max_lines lines of max_w pixels."""
    words = text.split()
    while size > 18:
        f = _font(text, heavy, size)
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
        size -= 2
    return _font(text, heavy, size), [text]


def _center_text(d, y, lines, f, fill, gap=1.12):
    for line in lines:
        l, t, r, b = d.textbbox((0, 0), line, font=f)
        d.text(((W - (r - l)) / 2 - l, y - t), line, font=f, fill=fill)
        y += f.size * gap
    return y


def make_poster(photo, title="", price="", headline="SPECIAL OFFER", tagline="", items=(), cta="Order now", backdrop=None):
    """photo: the user's product photo (PIL). backdrop: optional PIL image painted by the image model (no text in it).
    Returns a 1080x1350 RGB poster."""
    product = ai_cutout(photo) or cutout(photo)
    on_card = product is None
    product = card(photo) if on_card else product
    accent = accent_color(product)
    dark = mix(accent, (0, 0, 0), 0.55)

    bg = cover(backdrop) if backdrop is not None else gradient_bg(accent)
    # keep the top light and calm so the title reads on any backdrop
    veil = np.zeros((H, W, 4), np.uint8)
    veil[..., :3] = 255
    veil[..., 3] = (np.clip(1 - np.linspace(0, 1, H) / 0.42, 0, 1) ** 1.3 * 215).astype(np.uint8)[:, None]
    poster = Image.alpha_composite(bg.convert("RGBA"), Image.fromarray(veil))
    d = ImageDraw.Draw(poster)

    # headline pill
    y = 64
    if headline:
        f = _font(headline, True, 34)
        tw = f.getlength(headline.upper())
        d.rounded_rectangle([(W - tw) / 2 - 30, y, (W + tw) / 2 + 30, y + 62], 31, fill=accent)
        _center_text(d, y + 13, [headline.upper()], f, (255, 255, 255))
        y += 92
    # title + tagline
    if title:
        f, lines = _wrap(title, True, 88, W - 140, 2)
        y = _center_text(d, y, lines, f, dark, 1.08) + 6
    if tagline:
        f, lines = _wrap(tagline, False, 36, W - 180, 2)
        y = _center_text(d, y, lines, f, mix(dark, (90, 90, 90), 0.4), 1.2)

    # product
    band = 200 if items else 130
    top, bottom = max(y + 30, 390), H - band - 40
    r_badge = 140
    badge_left, badge_bottom = W - 2 * r_badge - 60, top + 2 * r_badge - 20   # the price badge's box (top right)
    if price:   # never let the product run under the badge: fit it left of the badge, or below it, whichever is bigger
        k_left = min((badge_left - 70) / product.width, (bottom - top) / product.height)
        k_below = min((W - 140) / product.width, (bottom - badge_bottom - 10) / product.height)
        if k_left >= k_below:
            k = k_left
            p = product.resize((max(1, int(product.width * k)), max(1, int(product.height * k))), Image.LANCZOS)
            px = max(50, (badge_left + 10 - p.width) // 2 + 20)
        else:
            k = k_below
            p = product.resize((max(1, int(product.width * k)), max(1, int(product.height * k))), Image.LANCZOS)
            px = (W - p.width) // 2
    else:
        k = min((W - 200) / product.width, (bottom - top) / product.height)
        p = product.resize((max(1, int(product.width * k)), max(1, int(product.height * k))), Image.LANCZOS)
        px = (W - p.width) // 2
    py = bottom - p.height
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse([px + p.width * 0.08, bottom - 26, px + p.width * 0.92, bottom + 26], fill=(0, 0, 0, 90))
    if on_card:
        ImageDraw.Draw(shadow).rounded_rectangle([px + 10, py + 18, px + p.width + 10, py + p.height + 18], 36, fill=(0, 0, 0, 60))
    poster = Image.alpha_composite(poster, shadow.filter(ImageFilter.GaussianBlur(18)))
    if not on_card:   # soft halo traced from the product's outline, so white bottles don't melt into a light backdrop
        halo = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        halo.paste(Image.new("RGBA", p.size, dark + (255,)), (px + 6, py + 10), p.getchannel("A").point(lambda a: a * 0.35))
        poster = Image.alpha_composite(poster, halo.filter(ImageFilter.GaussianBlur(14)))
    poster.paste(p, (px, py), p)
    d = ImageDraw.Draw(poster)

    # price badge: white ring, accent disc, "ONLY" + the price
    if price:
        r = r_badge
        cx, cy = W - r - 40, top + r - 40
        d.ellipse([cx - r - 10, cy - r - 10, cx + r + 10, cy + r + 10], fill=(255, 255, 255))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(228, 45, 62))   # sale red pops on any product colour
        f_small = _font("ONLY", True, 34)
        f_big, _ = _wrap(price, True, 120, 2 * r - 40, 1)
        _, t1, _, b1 = d.textbbox((0, 0), "ONLY", font=f_small)
        _, t2, _, b2 = d.textbbox((0, 0), price, font=f_big)
        total = (b1 - t1) + 14 + (b2 - t2)
        y0 = cy - total / 2
        for text, f, yy in (("ONLY", f_small, y0 - t1), (price, f_big, y0 + (b1 - t1) + 14 - t2)):
            l, _, rr, _ = d.textbbox((0, 0), text, font=f)
            d.text((cx - (rr - l) / 2 - l, yy), text, font=f, fill=(255, 255, 255))

    # bottom band: what's in the set + call to action
    d.rectangle([0, H - band, W, H], fill=dark)
    yb = H - band + 28
    items = [i for i in items if i][:6]
    if items:
        f = _font(" ".join(items), False, 28)
        cols = 2 if len(items) > 3 else 1
        rows = -(-len(items) // cols)
        colw = (W - 120) // cols
        for n, it in enumerate(items):
            fi, lines = _wrap("• " + it, False, 28, colw - 20, 1)
            d.text((60 + (n // rows) * colw, yb + (n % rows) * 38), lines[0], font=fi, fill=(255, 255, 255))
        if cta:
            f = _font(cta, True, 30)
            tw = f.getlength(cta.upper())
            d.rounded_rectangle([W - 60 - tw - 40, H - 72, W - 60, H - 22], 25, fill=accent)
            d.text((W - 60 - tw - 20, H - 66), cta.upper(), font=f, fill=(255, 255, 255))
    elif cta:
        f, lines = _wrap(cta.upper(), True, 52, W - 160, 1)
        _center_text(d, H - band / 2 - f.size / 2 - 4, lines, f, (255, 255, 255))
    return poster.convert("RGB")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("photo")
    ap.add_argument("--title", default="")
    ap.add_argument("--price", default="")
    ap.add_argument("--headline", default="SPECIAL OFFER")
    ap.add_argument("--tagline", default="")
    ap.add_argument("--items", nargs="*", default=[])
    ap.add_argument("--cta", default="Order now")
    ap.add_argument("--backdrop")
    ap.add_argument("-o", "--out", default="promo_poster.png")
    a = ap.parse_args()
    bd = Image.open(a.backdrop) if a.backdrop else None
    make_poster(Image.open(a.photo), a.title, a.price, a.headline, a.tagline, a.items, a.cta, bd).save(a.out)
    print("saved", a.out)
