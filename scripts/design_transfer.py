"""
Copy a reference poster's LAYOUT with the user's product and new words ("create a poster like image 1").

FongAI measures the reference instead of guessing:
  1. every text block: position, size, angle, color, heavy or light, and whether it sits on a box or badge
  2. the shapes behind text (black tags, starbursts, price boxes) are copied from the reference's pixels
  3. where the product stands (the user's cut-out product goes there)
  4. the chat model writes a new text for each block (same job, similar length)
  5. everything is redrawn at the same places with real fonts

  analysis = analyze(reference)          # PIL image
  poster = compose(analysis, {"t0": "boba!", ...}, product_rgba, width=1080)
"""
import numpy as np
from PIL import Image, ImageDraw, ImageFont

import cv2
from poster_text import BOLD_FONT, CJK_FONT, HEAVY_FONT, KHMER_FONT, _font_path, _geometry, find_text

LANGS = ["zh-Hans", "zh-Hant", "en-US"]


def _lum(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def _dist(a, b):
    return float(np.linalg.norm(np.array(a, float) - np.array(b, float)))


def _product_box(ref):
    """Where the product stands in the reference: the biggest object the cut-out model finds (None if it fails)."""
    try:
        from rembg import new_session, remove
        session = new_session("birefnet-general-lite")
        alpha = np.array(remove(ref, session=session, only_mask=True, post_process_mask=False).convert("L"))
    except Exception:   # noqa: BLE001
        return None
    n, labels, stats, _ = cv2.connectedComponentsWithStats((alpha > 128).astype(np.uint8), 8)
    if n <= 1:
        return None
    areas = stats[1:, cv2.CC_STAT_AREA]
    if areas.max() < 0.03 * ref.width * ref.height:
        return None
    # all the products together (a menu poster shows several drinks): every object at least 15% of the biggest
    keep = [i + 1 for i, a in enumerate(areas) if a >= areas.max() * 0.15]
    x0 = min(stats[i][0] for i in keep)
    y0 = min(stats[i][1] for i in keep)
    x1 = max(stats[i][0] + stats[i][2] for i in keep)
    y1 = max(stats[i][1] + stats[i][3] for i in keep)
    return (int(x0), int(y0), int(x1), int(y1))


def _inside(c, box, margin=0):
    return box and box[0] - margin <= c[0] <= box[2] + margin and box[1] - margin <= c[1] <= box[3] + margin


def analyze(ref):
    """Measure the reference poster. Returns {"size", "bg", "blocks": [...], "shapes": [...], "product": box}."""
    ref = ref.convert("RGB")
    if max(ref.size) < 1000:   # small screenshots: enlarge so the text reader can see small print
        k = 1000 / max(ref.size)
        ref = ref.resize((round(ref.width * k), round(ref.height * k)), Image.LANCZOS)
    rgb = np.array(ref)
    # the page color = the most common color (a screenshot's frame or a dark edge doesn't count)
    q = (rgb // 16).reshape(-1, 3)
    vals, counts = np.unique(q, axis=0, return_counts=True)
    top = vals[np.argmax(counts)]
    page = tuple(int(v) for v in np.median(rgb.reshape(-1, 3)[(q == top).all(1)], axis=0))
    # trim a screenshot frame: edge rows/columns with almost no page color
    near = np.linalg.norm(rgb.astype(float) - np.array(page, float), axis=2) < 40
    rows, cols = np.where(near.mean(1) > 0.08)[0], np.where(near.mean(0) > 0.08)[0]
    if len(rows) and len(cols):   # at most 4% per side: a frame is thin; a colored band (gradient top) is design
        W0, H0 = ref.size
        x0, y0 = min(int(cols[0]), int(W0 * 0.04)), min(int(rows[0]), int(H0 * 0.04))
        x1, y1 = max(int(cols[-1]) + 1, int(W0 * 0.96)), max(int(rows[-1]) + 1, int(H0 * 0.96))
        ref = ref.crop((x0, y0, x1, y1))
        rgb = np.array(ref)
    W, H = ref.size
    product = _product_box(ref)

    blocks, shapes = [], []
    for i, line in enumerate(find_text(ref, 0.2, LANGS)):
        w, h, angle, c = _geometry(line["quad"])
        if h < H * 0.012 or w < 4:
            continue
        x0, y0 = int(max(0, c[0] - w / 2)), int(max(0, c[1] - h / 2))
        x1, y1 = int(min(W, c[0] + w / 2)), int(min(H, c[1] + h / 2))
        box_px = rgb[y0:y1, x0:x1].reshape(-1, 3)
        if not len(box_px):
            continue
        pad = int(h * 0.35)
        ring = np.concatenate([rgb[max(0, y0 - pad):y0, x0:x1].reshape(-1, 3), rgb[y1:y1 + pad, x0:x1].reshape(-1, 3),
                               rgb[y0:y1, max(0, x0 - pad):x0].reshape(-1, 3), rgb[y0:y1, x1:x1 + pad].reshape(-1, 3)])
        local = tuple(int(v) for v in np.median(ring if len(ring) else box_px, axis=0))
        d = np.linalg.norm(box_px.astype(float) - np.array(local, float), axis=1)
        ink_px = box_px[d > max(40, np.percentile(d, 70))]
        ink = tuple(int(v) for v in np.median(ink_px, axis=0)) if len(ink_px) else (0, 0, 0)
        # text printed on the product (a logo on the cup) belongs to the product, not the layout
        if product and _inside(c, product, -h * 0.2) and x0 >= product[0] and x1 <= product[2]:
            continue
        boxed = _dist(local, page) > 60
        faded = abs(_lum(ink) - _lum(local)) < 45
        if not faded and abs(_lum(ink) - _lum(local)) < 150:
            ink = tuple(int(np.clip(l + (i - l) * 2.2, 0, 255)) for i, l in zip(ink, local))
        heavy = (d > 60).mean() > 0.38
        shape = None
        if boxed:   # the box / badge behind the text: same color around the text, connected to it
            gx0, gy0 = max(0, int(x0 - h * 2)), max(0, int(y0 - h * 2))
            gx1, gy1 = min(W, int(x1 + h * 2)), min(H, int(y1 + h * 2))
            area = rgb[gy0:gy1, gx0:gx1].astype(float)
            same = (np.linalg.norm(area - np.array(local, float), axis=2) < 45).astype(np.uint8)
            same = cv2.morphologyEx(same, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
            # the text itself is a hole in the shape: fill the text box so it's all one piece
            same[max(0, y0 - gy0):y1 - gy0, max(0, x0 - gx0):x1 - gx0] = 1
            n, labels, stats, _ = cv2.connectedComponentsWithStats(same, 8)
            lab = labels[int(c[1]) - gy0, int(c[0]) - gx0] if 0 <= int(c[1]) - gy0 < labels.shape[0] and 0 <= int(c[0]) - gx0 < labels.shape[1] else 0
            if lab:
                sx, sy, sw, sh, _ = stats[lab]
                box = (gx0 + sx, gy0 + sy, gx0 + sx + sw, gy0 + sy + sh)
                mask = Image.fromarray(((labels == lab) * 255).astype(np.uint8)[sy:sy + sh, sx:sx + sw])
                compact = sw * sh < 0.12 * W * H and (np.array(mask) > 0).mean() > 0.35
                if compact and product:
                    ix = max(0, min(box[2], product[2]) - max(box[0], product[0]))
                    iy = max(0, min(box[3], product[3]) - max(box[1], product[1]))
                    compact = ix * iy < 0.3 * sw * sh
                if compact:   # a real tag/badge stands out from what's around it (a gradient band doesn't)
                    bx0, by0, bx1, by1 = box
                    p2 = max(4, int(h * 0.5))
                    around = np.concatenate([rgb[max(0, by0 - p2):by0, bx0:bx1].reshape(-1, 3), rgb[by1:by1 + p2, bx0:bx1].reshape(-1, 3),
                                             rgb[by0:by1, max(0, bx0 - p2):bx0].reshape(-1, 3), rgb[by0:by1, bx1:bx1 + p2].reshape(-1, 3)])
                    compact = len(around) > 0 and _dist(np.median(around, axis=0), local) > 70
                same_as = next((s for s in shapes if _dist(s["box"][:2], box[:2]) < h and _dist(s["box"][2:], box[2:]) < h), None)
                if compact and same_as is None:
                    shapes.append({"box": box, "mask": mask, "color": local})
                shape = box if compact else None
        cx_shape = (shape[0] + shape[2]) / 2 if shape else None
        blocks.append({"id": f"t{len(blocks)}", "text": line["text"], "box": (x0, y0, x1, y1), "h": h, "angle": angle,
                       "ink": ink, "boxed": shape is not None, "faded": faded, "heavy": heavy,
                       "center": bool(shape and abs(cx_shape - c[0]) < (shape[2] - shape[0]) * 0.12)})
    return {"size": (W, H), "bg": page, "blocks": blocks, "shapes": shapes, "product": product, "ref": ref}


def describe(analysis):
    """The blocks as the chat model sees them: id, old text, size and place, so it can write a matching new text."""
    W, H = analysis["size"]
    hs = sorted((b["h"] for b in analysis["blocks"]), reverse=True)
    out = []
    for b in analysis["blocks"]:
        cx, cy = (b["box"][0] + b["box"][2]) / 2 / W, (b["box"][1] + b["box"][3]) / 2 / H
        where = ("top" if cy < 0.33 else "bottom" if cy > 0.66 else "middle") + "-" + ("left" if cx < 0.4 else "right" if cx > 0.6 else "center")
        size = "huge headline" if b["h"] >= hs[0] * 0.8 else "big" if b["h"] >= hs[0] * 0.4 else "small"
        kind = "faded background word" if b["faded"] else "text on a colored box/badge" if b["boxed"] else "text"
        out.append(f'{b["id"]}: "{b["text"]}"  ({size}, {where}, {kind}, {len(b["text"])} characters)')
    return "\n".join(out)


def _font(text, heavy, size):
    if any("ក" <= ch <= "៿" for ch in text):
        name = KHMER_FONT
    elif any("　" <= ch <= "鿿" or "＀" <= ch <= "￯" for ch in text):
        name = CJK_FONT
    else:
        name = HEAVY_FONT if heavy else BOLD_FONT
    path = _font_path(name) or _font_path(BOLD_FONT)
    return ImageFont.truetype(path, max(8, int(size))) if path else ImageFont.load_default()


def _fit(text, heavy, h, max_w):
    """Font whose letters are about h tall (like the reference), smaller if the new text is too wide."""
    size = h
    f = _font(text, heavy, size)
    hb = f.getbbox(text)
    if hb[3] - hb[1] > 0:
        size = size * h * 0.92 / (hb[3] - hb[1])
    f = _font(text, heavy, size)
    while f.getlength(text) > max_w and size > 10:
        size *= 0.93
        f = _font(text, heavy, size)
    return f


def compose(analysis, texts, product=None, width=1080):
    """texts: {block id: new text} ('' hides a block). product: RGBA cut-out or None. Returns the new poster."""
    W, H = analysis["size"]
    k = width / W
    out_w, out_h = width, round(H * k)
    img = Image.new("RGB", (out_w, out_h), analysis["bg"])
    S = lambda v: int(round(v * k))

    for b in analysis["blocks"]:   # big faded words behind everything
        t = texts.get(b["id"], "")
        if b["faded"] and t:
            f = _fit(t, True, b["h"] * k, (b["box"][2] - b["box"][0]) * k * 1.3)
            layer = Image.new("RGBA", (int(f.getlength(t)) + 40, int(f.size * 1.5)), (0, 0, 0, 0))
            ImageDraw.Draw(layer).text((20, 0), t, font=f, fill=b["ink"] + (255,))
            layer = layer.rotate(-b["angle"], expand=True, resample=Image.BICUBIC)
            img.paste(layer, (S((b["box"][0] + b["box"][2]) / 2) - layer.width // 2, S((b["box"][1] + b["box"][3]) / 2) - layer.height // 2), layer)

    if product is not None and analysis["product"]:   # the user's product where the reference's product stood
        x0, y0, x1, y1 = (S(v) for v in analysis["product"])
        r = min((x1 - x0) * 1.08 / product.width, (y1 - y0) * 1.04 / product.height)
        p = product.resize((max(1, int(product.width * r)), max(1, int(product.height * r))), Image.LANCZOS)
        img.paste(p, ((x0 + x1) // 2 - p.width // 2, y1 - p.height), p)

    for s in analysis["shapes"]:   # tags, badges, price boxes: the reference's own shapes
        x0, y0, x1, y1 = (S(v) for v in s["box"])
        m = s["mask"].resize((max(1, x1 - x0), max(1, y1 - y0)), Image.LANCZOS)
        img.paste(Image.new("RGB", m.size, s["color"]), (x0, y0), m)

    d = ImageDraw.Draw(img)
    for b in analysis["blocks"]:
        t = texts.get(b["id"], "")
        if not t or b["faded"]:
            continue
        x0, y0, x1, y1 = (v * k for v in b["box"])
        room = (x1 - x0) * (1.0 if b["boxed"] else 1.35)
        if not b["boxed"] and not b["center"]:
            room = max(room, min(out_w - x0 - 30 * k, (x1 - x0) * 1.8)) if b["h"] * k > out_h * 0.06 else room
        f = _fit(t, b["heavy"], b["h"] * k, room)
        l, top, r, bot = d.textbbox((0, 0), t, font=f)
        tx = (x0 + x1) / 2 - (r - l) / 2 - l if b["center"] or b["boxed"] else x0 - l
        ty = (y0 + y1) / 2 - (bot + top) / 2
        if abs(b["angle"]) > 3:
            layer = Image.new("RGBA", (int(r - l) + 20, int(bot - top) + 20), (0, 0, 0, 0))
            ImageDraw.Draw(layer).text((10 - l, 10 - top), t, font=f, fill=b["ink"] + (255,))
            layer = layer.rotate(-b["angle"], expand=True, resample=Image.BICUBIC)
            img.paste(layer, (int((x0 + x1) / 2 - layer.width / 2), int((y0 + y1) / 2 - layer.height / 2)), layer)
            d = ImageDraw.Draw(img)
        else:
            d.text((tx, ty), t, font=f, fill=b["ink"])
    return img
