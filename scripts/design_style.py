"""
Read the style of a reference design ("make it like image 2") so FongAI's layout can follow it:
colors come from the pixels (reliable), the look (lettering, layout, mood) from the vision model.

style = {"bg": (r,g,b), "text": (r,g,b), "accent": (r,g,b), "lettering": "brush", "layout": "collage",
         "playful": True, "text_position": "bottom", "mood": "fun, summery"}
"""
import json
import re

import cv2
import numpy as np

from poster_text import _font_path

# lettering style -> macOS font file (first one found wins)
LETTERING = {
    "brush": ["MarkerFelt.ttc#1", "SignPainter.ttc#1", "Brush Script.ttf"],   # #1 = the second face in the .ttc (Wide / Semibold)
    "marker": ["MarkerFelt.ttc#1", "Chalkduster.ttf"],
    "script": ["SnellRoundhand.ttc", "Brush Script.ttf"],
    "handwritten": ["Bradley Hand Bold.ttf", "Noteworthy.ttc", "MarkerFelt.ttc"],
    "serif": ["Didot.ttc", "Bodoni 72.ttc", "Georgia Bold.ttf"],
    "bold-sans": ["Arial Black.ttf", "Impact.ttf"],
    "condensed": ["DIN Condensed Bold.ttf", "Impact.ttf"],
    "retro": ["Rockwell.ttc", "Phosphate.ttc", "Copperplate.ttc"],
    "chalk": ["Chalkduster.ttf", "Chalkboard.ttc"],
}
SMALL_FONT = ["DIN Condensed Bold.ttf", "Avenir Next Condensed.ttc", "Arial Bold.ttf"]   # small print, top labels
ACCENT_SCRIPT = ["Brush Script.ttf", "SnellRoundhand.ttc"]                                # the little script word

STYLE_PROMPT = """Look at this poster's DESIGN STYLE (not what it is about). Find its BIGGEST text, the headline, and ignore small text.
Reply with JSON only:
{"lettering": "the BIGGEST text's lettering: brush (painted, rough strokes), script (joined-up cursive), handwritten, serif, bold-sans, condensed, retro or chalk",
 "heavy": true if the BIGGEST text has thick, heavy strokes, false if thin,
 "text_position": "where the BIGGEST text is: top, middle or bottom",
 "layout": "collage (objects arranged playfully), centered (one product in the middle), split (picture one side, text other side) or full-photo",
 "playful": true or false (tilted objects, stickers, doodles, fun)}"""


def _resolve(name):
    """'MarkerFelt.ttc#1' -> ('/System/.../MarkerFelt.ttc', 1); None if the font isn't on this Mac."""
    file, _, idx = name.partition("#")
    path = _font_path(file)
    return (path, int(idx or 0)) if path else None


def font_file(kind):
    for name in LETTERING.get(kind, []) + LETTERING["bold-sans"]:
        if _resolve(name):
            return _resolve(name)
    return None


def first_font(names):
    return next((_resolve(n) for n in names if _resolve(n)), None)


def _lum(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def palette(img):
    """Background = the color of the edges; accent = the strongest vivid color that isn't the background;
    text = the darkest (or lightest) strong color that reads on the background."""
    rgb = np.array(img.convert("RGB").resize((240, int(240 * img.height / max(img.width, 1)))))
    h, w, _ = rgb.shape
    b = max(2, int(min(h, w) * 0.06))
    edge = np.concatenate([rgb[:b].reshape(-1, 3), rgb[-b:].reshape(-1, 3), rgb[:, :b].reshape(-1, 3), rgb[:, -b:].reshape(-1, 3)])
    bg = tuple(int(v) for v in np.median(edge, axis=0))
    px = rgb.reshape(-1, 3).astype(np.float32)
    far = px[np.linalg.norm(px - np.array(bg), axis=1) > 60]   # everything that isn't background
    accent, text = None, None
    if len(far) > 50:
        hsv = cv2.cvtColor(far.reshape(-1, 1, 3).astype(np.uint8), cv2.COLOR_RGB2HSV).reshape(-1, 3)
        vivid = far[(hsv[:, 1] > 90) & (hsv[:, 2] > 60)]
        if len(vivid) > 30:
            k = min(4, len(vivid))
            _, labels, centers = cv2.kmeans(vivid, k, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0),
                                            3, cv2.KMEANS_PP_CENTERS)
            counts = np.bincount(labels.ravel(), minlength=k)
            sat = cv2.cvtColor(np.uint8([centers]), cv2.COLOR_RGB2HSV)[0][:, 1]
            accent = tuple(int(v) for v in centers[int(np.argmax(counts * (sat / 255.0) ** 2))])
        dark = far[np.array([_lum(c) for c in far]) < 80]
        light = far[np.array([_lum(c) for c in far]) > 200]
        if _lum(bg) > 140 and len(dark) > 20:
            text = tuple(int(v) for v in np.median(dark, axis=0))
        elif _lum(bg) <= 140 and len(light) > 20:
            text = tuple(int(v) for v in np.median(light, axis=0))
    text = text or ((34, 30, 28) if _lum(bg) > 140 else (250, 248, 244))
    accent = accent or ((200, 40, 30) if _lum(bg) > 140 else (255, 196, 40))
    return {"bg": bg, "text": text, "accent": accent}


def read_style(img, ask_vision=None):
    """img: the reference design (PIL). ask_vision(prompt) -> text from the vision model, or None to skip it."""
    style = palette(img)
    style.update(lettering="bold-sans", layout="centered", playful=False, text_position="bottom", mood="")
    if ask_vision:
        try:
            m = re.search(r"\{.*\}", ask_vision(STYLE_PROMPT), re.S)
            seen = json.loads(m.group(0)) if m else {}
        except Exception:   # noqa: BLE001  (vision model missing or odd answer: colors alone still work)
            seen = {}
        if seen.get("lettering") in LETTERING:
            style["lettering"] = seen["lettering"]
        if seen.get("layout") in ("collage", "centered", "split", "full-photo"):
            style["layout"] = seen["layout"]
        if seen.get("text_position") in ("top", "middle", "bottom"):
            style["text_position"] = seen["text_position"]
        style["playful"] = bool(seen.get("playful"))
        if seen.get("heavy") and style["lettering"] in ("script", "serif", "handwritten"):
            style["lettering"] = "brush" if style["lettering"] != "serif" else "bold-sans"   # thick strokes: not a thin script
        if style["playful"] and style["lettering"] in ("bold-sans", "condensed"):
            style["lettering"] = "marker"   # a playful, handmade poster: hand-drawn letters, not corporate Arial Black
    return style
