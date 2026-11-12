"""
Swap the words on a poster without redrawing it: find each text line (Apple Vision OCR, runs on-device),
erase it (OpenCV inpainting), and write the new words in a real font, matching size, colour and tilt.
Everything else in the image (logo, photos, colours) stays pixel-for-pixel the same.

  python scripts/poster_text.py poster.png              # list the text it finds
  python scripts/poster_text.py poster.png 1="WINTER SALE" 3="11 - 15 Dec 2026" -o out.png
"""
import math
import os

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT_DIRS = ["/System/Library/Fonts/Supplemental", "/Library/Fonts", "/System/Library/Fonts"]
HEAVY_FONT = "Arial Black.ttf"   # big headline text
BOLD_FONT = "Arial Bold.ttf"      # everything else
KHMER_FONT = "Khmer Sangam MN.ttf"
CJK_FONT = "Hiragino Sans GB.ttc"


def _font_path(name):
    for d in FONT_DIRS:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


def find_text(image, min_confidence=0.3):
    """Lines of text in a PIL image: [{"text", "quad": [(x, y) x4: top-left, top-right, bottom-right, bottom-left], "confidence"}]."""
    import Foundation
    import Vision
    image = image.convert("RGB")
    w, h = image.size
    import io
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    data = Foundation.NSData.dataWithBytes_length_(buf.getvalue(), len(buf.getvalue()))
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setUsesLanguageCorrection_(False)
    handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, None)
    ok, err = handler.performRequests_error_([req], None)
    if not ok:
        raise RuntimeError(f"text recognition failed: {err}")
    lines = []
    for obs in req.results() or []:
        cand = obs.topCandidates_(1)[0]
        text = str(cand.string()).strip()
        if not text or cand.confidence() < min_confidence:
            continue
        rect, _ = cand.boundingBoxForRange_error_(Foundation.NSMakeRange(0, len(cand.string())), None)
        rect = rect or obs
        # Vision uses 0-1 coordinates with the origin at the bottom left
        pt = lambda p: (p.x * w, (1 - p.y) * h)
        quad = [pt(rect.topLeft()), pt(rect.topRight()), pt(rect.bottomRight()), pt(rect.bottomLeft())]
        lines.append({"text": text, "quad": quad, "confidence": round(float(cand.confidence()), 2)})
    lines.sort(key=lambda l: (min(p[1] for p in l["quad"]), min(p[0] for p in l["quad"])))
    return lines


def _geometry(quad):
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = quad
    width = math.hypot(x1 - x0, y1 - y0)
    height = (math.hypot(x3 - x0, y3 - y0) + math.hypot(x2 - x1, y2 - y1)) / 2
    angle = math.degrees(math.atan2(y1 - y0, x1 - x0))
    center = ((x0 + x1 + x2 + x3) / 4, (y0 + y1 + y2 + y3) / 4)
    return width, height, angle, center


def _grow(quad, pad):
    """Push each corner outwards from the centre by `pad` pixels (covers outlines and shadows)."""
    cx = sum(p[0] for p in quad) / 4
    cy = sum(p[1] for p in quad) / 4
    out = []
    for x, y in quad:
        d = math.hypot(x - cx, y - cy) or 1
        out.append((x + (x - cx) / d * pad * 1.4, y + (y - cy) / d * pad * 1.4))
    return out


def _colors(arr, quad, pad):
    """(text colour, background colour) for one line: background = ring just outside the text,
    text = the pixels inside that differ most from it."""
    h, w = arr.shape[:2]
    inner = np.zeros((h, w), np.uint8)
    cv2.fillPoly(inner, [np.int32(quad)], 255)
    outer = np.zeros((h, w), np.uint8)
    cv2.fillPoly(outer, [np.int32(_grow(quad, pad * 2.5))], 255)
    ring = arr[(outer > 0) & (inner == 0)]
    bg = np.median(ring, axis=0) if len(ring) else np.array([255, 255, 255])
    px = arr[inner > 0].astype(float)
    if not len(px):
        return (255, 255, 255), tuple(int(c) for c in bg)
    dist = np.linalg.norm(px - bg, axis=1)
    far = px[dist >= np.percentile(dist, 70)].astype(np.float32)   # text pixels, not anti-aliased edges
    if len(far) >= 8:   # two-colour text (green words + red "50%"): use the main colour, don't blend them
        _, labels, centers = cv2.kmeans(far, 2, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0),
                                        3, cv2.KMEANS_PP_CENTERS)
        main = centers[np.bincount(labels.ravel(), minlength=2).argmax()]
    else:
        main = np.median(far, axis=0)
    return tuple(int(c) for c in main), tuple(int(c) for c in bg)


def _fit_font(text, path, box_w, box_h):
    """Largest size whose letters are about as tall as the old ones and no wider than the old line."""
    size = max(8, int(box_h * 1.25))
    while size > 8:
        font = ImageFont.truetype(path, size)
        l, t, r, b = font.getbbox(text)
        if r - l <= box_w * 1.02 and b - t <= box_h * 1.05:
            return font
        size -= 1
    return ImageFont.truetype(path, 8)


def replace_text(image, lines, changes):
    """changes: {line index: new text} ("" just erases). Returns a new PIL image."""
    image = image.convert("RGB")
    arr = np.array(image)
    picked = [(lines[i], new) for i, new in changes.items() if 0 <= i < len(lines)]
    styles = []
    mask = np.zeros(arr.shape[:2], np.uint8)
    for line, new in picked:
        _, height, _, _ = _geometry(line["quad"])
        pad = max(2, height * 0.12)
        styles.append(_colors(arr, line["quad"], pad))
        cv2.fillPoly(mask, [np.int32(_grow(line["quad"], pad))], 255)
    erased = cv2.inpaint(arr, mask, 5, cv2.INPAINT_TELEA)
    out = Image.fromarray(erased)
    for (line, new), (fg, bg) in zip(picked, styles):
        if not new.strip():
            continue
        width, height, angle, (cx, cy) = _geometry(line["quad"])
        heavy = height > image.height * 0.08
        if any("\u1780" <= c <= "\u17ff" for c in new):        # Arial has no Khmer letters
            path = _font_path(KHMER_FONT)
        elif any("\u3000" <= c <= "\u9fff" for c in new):
            path = _font_path(CJK_FONT)
        else:
            path = _font_path(HEAVY_FONT if heavy else BOLD_FONT) or _font_path(BOLD_FONT)
        font = _fit_font(new, path, width, height) if path else ImageFont.load_default()
        l, t, r, b = font.getbbox(new)
        stroke = max(1, round(font.size / 18)) if heavy else 0   # thin dark edge keeps headlines readable
        layer = Image.new("RGBA", (r - l + 4 * stroke + 4, b - t + 4 * stroke + 4), (0, 0, 0, 0))
        dark = tuple(int(c * 0.35) for c in bg)
        ImageDraw.Draw(layer).text((2 * stroke + 2 - l, 2 * stroke + 2 - t), new, font=font, fill=fg + (255,),
                                   stroke_width=stroke, stroke_fill=dark + (255,))
        layer = layer.rotate(-angle, resample=Image.BICUBIC, expand=True)
        out.paste(layer, (int(cx - layer.width / 2), int(cy - layer.height / 2)), layer)
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("changes", nargs="*", help='LINE="new text"')
    ap.add_argument("-o", "--out", default="poster_edited.png")
    a = ap.parse_args()
    img = Image.open(a.image)
    found = find_text(img)
    for i, l in enumerate(found):
        print(f"{i}: {l['text']!r}  ({l['confidence']})")
    if a.changes:
        ch = {int(k): v for k, v in (c.split("=", 1) for c in a.changes)}
        replace_text(img, found, ch).save(a.out)
        print("saved", a.out)
