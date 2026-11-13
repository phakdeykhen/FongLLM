"""
Marketing banner (1600x900, for web, Facebook, YouTube or email headers). The chat model plans the words, the
image model paints only the hero picture (it can't spell), and every word is typeset here in a real font, so the
text is always sharp and correct: brand, eyebrow pill, headline with a highlighted phrase, subheadline,
feature chips and a call-to-action button.

  python scripts/banner.py plan.json hero.png -o banner.png
"""
import re

import numpy as np
from PIL import Image, ImageDraw

from promo_poster import _font, _wrap, cover, mix

W, H = 1600, 900
LEFT, COL = 84, 760   # text column: x and width


def hex_color(s, default=(37, 99, 235)):
    m = re.fullmatch(r"#?([0-9a-f]{6})", str(s or "").strip(), re.I)
    return tuple(int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4)) if m else default


# Words that make the image model try to paint lettering (it can't spell: you get fake text like "BAREB")
WORDY = re.compile(r"\b(banners?|posters?|signs?|signboards?|billboards?|flyers?|texts?|words?|letters?|logos?|titles?|"
                   r"headlines?|captions?|labels?|brand names?|typography|slogans?|ads?|advert\w*|prompts?|briefs?|"
                   r"generators?|templates?|mock-?ups?)\b", re.I)


def hero_prompt(subject):
    """What the image model paints: the picture only, standing on the right, empty space on the left for the text."""
    if WORDY.search(subject) or not subject.strip():   # a picture of lettering: paint a person instead
        subject = "a smiling young professional working on a laptop in a modern bright office"
    return (f"{subject}, placed on the right side of the frame, empty dark background on the left side, professional "
            "advertising photography, cinematic lighting, sharp focus, high detail, no text, no letters, no words, "
            "no logo, no watermark")


def _background(accent):
    deep = mix(accent, (4, 8, 24), 0.82)
    mid = mix(accent, (4, 8, 24), 0.45)
    x = np.linspace(0, 1, W)[None, :, None]
    y = np.linspace(0, 1, H)[:, None, None]
    t = np.clip(0.75 * x + 0.25 * y, 0, 1)
    arr = np.array(deep) * (1 - t) + np.array(mid) * t
    return Image.fromarray(np.broadcast_to(arr, (H, W, 3)).astype(np.uint8))


def _place_hero(bg, hero):
    """The hero picture fills the right ~60% and fades into the background toward the text."""
    size = (int(W * 0.62), H)
    pic = cover(hero, size)
    ramp = np.clip(np.linspace(-0.15, 1.25, size[0]), 0, 1) ** 1.4   # transparent at its left edge
    mask = Image.fromarray((np.broadcast_to(ramp[None, :], (size[1], size[0])) * 255).astype(np.uint8))
    bg.paste(pic, (W - size[0], 0), mask)


def _pill(d, xy, text, f, fill, color, pad=(22, 10)):
    l, t, r, b = d.textbbox((0, 0), text, font=f)
    w, h = r - l + pad[0] * 2, f.size + pad[1] * 2
    x, y = xy
    d.rounded_rectangle((x, y, x + w, y + h), radius=h // 2, fill=fill)
    d.text((x + pad[0] - l, y + (h - (b - t)) / 2 - t), text, font=f, fill=color)
    return w, h


def _headline(d, x, y, text, highlight, max_w, color, accent):
    """Big headline; the words of `highlight` are drawn in the accent color. Returns the y below it."""
    f, lines = _wrap(text, True, 80, max_w, 3)
    marked = set(w.lower().strip(",.!?") for w in (highlight or "").split())
    space = f.getlength(" ")
    for line in lines:
        cx = x
        for word in line.split():
            d.text((cx, y), word, font=f, fill=accent if word.lower().strip(",.!?") in marked else color)
            cx += f.getlength(word) + space
        y += f.size * 1.08
    return y


def make_banner(plan, hero=None):
    """plan: {brand, eyebrow, headline, highlight, subheadline, features: [..], cta, color}. hero: PIL image or None."""
    text = lambda k: str(plan.get(k) or "").strip()
    accent = hex_color(plan.get("color"))
    bright = mix(accent, (255, 255, 255), 0.45)
    img = _background(accent)
    if hero is not None:
        _place_hero(img, hero)
    glow = Image.new("RGB", (W, H), (0, 0, 0))   # soft light behind the headline
    ImageDraw.Draw(glow).ellipse((-300, 120, 700, 820), fill=mix(accent, (0, 0, 0), 0.6))
    img = Image.blend(img, Image.composite(img, glow, Image.new("L", (W, H), 170)), 0.35)
    d = ImageDraw.Draw(img)

    y = 64
    brand = text("brand")
    if brand:   # brand mark: a rounded square with the first letter, then the name
        d.rounded_rectangle((LEFT, y, LEFT + 58, y + 58), radius=14, fill=bright)
        f = _font(brand[0], True, 36)
        l, t, r, b = d.textbbox((0, 0), brand[0].upper(), font=f)
        d.text((LEFT + 29 - (r - l) / 2 - l, y + 29 - (b - t) / 2 - t), brand[0].upper(), font=f, fill=mix(accent, (0, 0, 0), 0.6))
        fb, _ = _wrap(brand, False, 40, COL - 80, 1)
        d.text((LEFT + 76, y + 6), brand, font=fb, fill=(255, 255, 255))
    y += 110

    if text("eyebrow"):
        f = _font(text("eyebrow"), False, 26)
        _, h = _pill(d, (LEFT, y), text("eyebrow"), f, accent, (255, 255, 255))
        y += h + 26

    y = _headline(d, LEFT, y, text("headline") or brand or "Your headline", text("highlight"), COL, (255, 255, 255), bright)
    y += 40

    if text("subheadline"):
        f, lines = _wrap(text("subheadline"), False, 31, COL - 40, 3)
        for line in lines:
            d.text((LEFT, y), line, font=f, fill=(206, 216, 238))
            y += f.size * 1.32
    y += 30

    if text("cta"):   # call-to-action button
        f = _font(text("cta"), True, 32)
        label = text("cta") + "  →"
        _pill(d, (LEFT, y), label, f, (255, 184, 28), (24, 24, 40), pad=(38, 20))

    feats = [str(x).strip() for x in plan.get("features") or [] if str(x).strip()][:4]
    if feats:   # feature chips along the bottom: frosted rounded pills with a drawn check mark
        f = _font(" ".join(feats), False, 24)
        chips, x, yb, h = [], LEFT, H - 96, 54
        for ft in feats:
            w = f.getlength(ft) + 78
            if x + w > W - 40:
                break
            chips.append((x, ft, w))
            x += w + 14
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        for x, ft, w in chips:
            ld.rounded_rectangle((x, yb, x + w, yb + h), radius=h // 2, fill=(255, 255, 255, 30), outline=(255, 255, 255, 80), width=2)
        img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")
        d = ImageDraw.Draw(img)
        for x, ft, w in chips:
            cx, cy = x + 30, yb + h / 2
            d.line([(cx - 9, cy), (cx - 3, cy + 7), (cx + 10, cy - 8)], fill=bright, width=4, joint="curve")
            l, t, r, b = d.textbbox((0, 0), ft, font=f)
            d.text((x + 52 - l, yb + (h - (b - t)) / 2 - t), ft, font=f, fill=(255, 255, 255))
    return img


if __name__ == "__main__":
    import argparse
    import json
    p = argparse.ArgumentParser()
    p.add_argument("plan")
    p.add_argument("hero", nargs="?")
    p.add_argument("-o", default="banner.png")
    a = p.parse_args()
    make_banner(json.load(open(a.plan)), Image.open(a.hero) if a.hero else None).save(a.o)
    print(a.o)
