"""FongAI file maker: "create a PDF / Word / Excel / PowerPoint / React / HTML ..." -> a real file plus a preview page.

The chat model writes simple text (Markdown, CSV or code). Python turns it into the file:
  pdf   Markdown -> styled A4 HTML -> PDF (headless Google Chrome)
  docx  Markdown -> Word (python-docx)
  xlsx  CSV      -> Excel (openpyxl)
  pptx  Markdown -> PowerPoint (python-pptx), "## " starts each slide
  react one JSX component (export default function App)
  html  one self-contained HTML page
Each file goes into out/files/<id>/ with preview.html (what the side panel shows; for PDF the PDF itself).
"""
import csv
import html
import io
import json
import os
import re
import subprocess
import time

import markdown as md

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FILES_DIR = os.environ.get("MINIMIND_FILES_DIR", os.path.join(ROOT, "out", "files"))
CHROME = os.environ.get("CHROME_BIN", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

KINDS = {
    "pdf": {"ext": "pdf", "label": "PDF", "group": "Document"},
    "docx": {"ext": "docx", "label": "Word", "group": "Document"},
    "xlsx": {"ext": "xlsx", "label": "Excel", "group": "Spreadsheet"},
    "pptx": {"ext": "pptx", "label": "PowerPoint", "group": "Presentation"},
    "react": {"ext": "jsx", "label": "React", "group": "Code"},
    "html": {"ext": "html", "label": "HTML", "group": "Code"},
}
_KIND_WORDS = [   # first match wins, so "a PDF of the slides" stays a PDF only when "pdf" is checked before "slides"
    ("pdf", r"\bpdfs?\b"),
    ("pptx", r"\b(power ?points?|pptx?|slides?|slide ?decks?|decks?|presentations?)\b"),
    ("xlsx", r"\b(excel|xlsx|spread ?sheets?|worksheets?|csv)\b"),
    ("docx", r"\b(docx|ms ?word|microsoft word|microsoft|word (document|doc|file|format)s?|(in|as|to) word)\b"),
    ("react", r"\b(react(js)?|jsx|tsx|react component)\b"),
    ("html", r"\b(html|web ?page|website|landing ?page)\b"),
]
MAKE = re.compile(r"\b(creae?te?|creaet|make|write|generate|build|design|draft|prepare|produce|give me|export|save|"
                  r"convert|turn|put|need|want|do)\b|\bas (an? )?\w+ file\b|បង្កើត|ធ្វើ|做|生成|写", re.I)
PICTURE = re.compile(r"\b(png|jpe?g|logo|icon|picture|image|photo|poster|drawing|wallpaper|banner)s?\b", re.I)
FILE_MARK = "Preview it on the right"   # every file reply says this, so "change X" can follow up on that file
LAST = {}   # the newest file: {"kind", "source", "title"} (local app, one user)


def detect_kind(text):
    """'create a quotation as PDF' -> 'pdf'; None when no file is asked for."""
    if not MAKE.search(text):
        return None
    for kind, pat in _KIND_WORDS:
        if re.search(pat, text, re.I):
            # "a logo for my website" / "an image for my landing page" is a picture, not a code file
            if kind in ("html", "react") and PICTURE.search(text) and not re.search(r"\b(html|jsx|react|code)\b", text, re.I):
                return None
            return kind
    return None


# ---------- what the model is asked to write ----------
_DOC = ("Write the complete content of the document below in Markdown. Start with '# Title'. Use '## ' for sections, "
        "GitHub tables (| a | b |) for items, prices and totals, '- ' for bullet lists, **bold** for labels. Do the maths "
        "yourself and show totals. Fill in realistic details; for unknown facts (names, dates, phone) use blanks like ______. "
        "Output ONLY the Markdown: no explanations, no code fences.")
PROMPTS = {
    "pdf": _DOC,
    "docx": _DOC,
    "xlsx": ("Write the spreadsheet below as CSV. First row = column headers. Plain numbers (no $ or commas inside numbers). "
             "Add a final TOTAL row where it makes sense, with the total already calculated. Output ONLY the CSV."),
    "pptx": ("Write the presentation below in Markdown. First line: '# Presentation title', next line: a short subtitle. "
             "Then each slide starts with '## Slide title' followed by 3-5 bullet points '- ...' (short, max 12 words each). "
             "Make 6-10 slides. Output ONLY the Markdown."),
    "react": ("Write ONE self-contained React component file for the request below. Use `export default function App()`. "
              "Only import from 'react' (useState, useEffect, ...). No other libraries, no CSS files: put styles in a "
              "<style> tag inside the JSX or in inline style objects. Make it look modern and polished. Output ONLY the code."),
    "html": ("Write ONE complete self-contained HTML file for the request below, with all CSS in a <style> tag and any JS in "
             "a <script> tag. No external files. Make it modern, polished and responsive. Output ONLY the HTML."),
}
REVISE = ("Here is the current {label} source, between <<< and >>>:\n<<<\n{source}\n>>>\n\nApply the user's change below and "
          "output the FULL updated source in exactly the same format. Change only what the user asks. Output ONLY the source.")


def strip_fences(text):
    m = re.search(r"```[\w+-]*\n(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip()


def write_source(kind, ask, ollama_url, model, history=(), revise=False, on_progress=None):
    """Asks the Ollama model for the file's source text. on_progress(words) is called while it writes."""
    import requests
    if revise and LAST:
        user = REVISE.format(label=KINDS[kind]["label"], source=LAST["source"]) + "\n\nUser's change: " + ask
    else:
        user = PROMPTS[kind] + "\n\nRequest: " + ask
    msgs = [{"role": "system", "content": "You are Fong AI. You write files exactly in the format asked, nothing else."}]
    msgs += [m for m in history if m["role"] == "user"][-2:] + [{"role": "user", "content": user}]
    r = requests.post(f"{ollama_url}/api/chat", stream=True, timeout=900, json={
        "model": model, "messages": msgs, "stream": True,
        "options": {"temperature": 0.3, "num_predict": 4096, "num_ctx": 8192}})
    r.raise_for_status()
    out, last = "", 0
    for line in r.iter_lines():
        if line:
            out += json.loads(line).get("message", {}).get("content", "")
            if on_progress and time.time() - last > 0.7:
                last = time.time()
                on_progress(len(out.split()))
    return strip_fences(out)


# ---------- Markdown helpers ----------
DOC_CSS = """
@page { size: A4; margin: 16mm 15mm; }
* { box-sizing: border-box; }
body { font: 10.5pt/1.5 -apple-system, "Helvetica Neue", Arial, "Noto Sans Khmer", sans-serif; color: #1f2937; margin: 0; }
.page { max-width: 210mm; margin: 0 auto; padding: 0; background: #fff; }
h1 { color: #1e3a6e; font-size: 22pt; margin: 0 0 4mm; padding-bottom: 3mm; border-bottom: 2px solid #1e3a6e; }
h2 { color: #1e3a6e; font-size: 13pt; margin: 6mm 0 2mm; padding-bottom: 1mm; border-bottom: 1px solid #d5dbe5; }
h3 { font-size: 11pt; margin: 4mm 0 1mm; }
p { margin: 1.5mm 0; }
ul, ol { margin: 1mm 0 2mm; padding-left: 6mm; }
table { width: 100%; border-collapse: collapse; margin: 3mm 0; font-size: 9.5pt; }
th { background: #1e3a6e; color: #fff; text-align: left; padding: 2mm 2.5mm; }
td { border: 1px solid #d5dbe5; padding: 1.8mm 2.5mm; vertical-align: top; }
tr:nth-child(even) td { background: #f5f7fb; }
tr:last-child td strong, td:has(strong:only-child) { font-weight: 700; }
code { background: #f1f3f7; padding: 0 1mm; border-radius: 2px; }
blockquote { margin: 2mm 0; padding: 1mm 4mm; border-left: 3px solid #1e3a6e; color: #475569; }
"""
SCREEN_CSS = """
@media screen { html { background: #e9ecf1; } body { padding: 24px 12px; }
  .page { padding: 16mm 15mm; min-height: 297mm; box-shadow: 0 2px 16px rgba(0,0,0,.12); } }
"""


def md_to_html_page(text, title):
    body = md.markdown(text, extensions=["tables", "sane_lists"])
    return (f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(title)}</title><style>{DOC_CSS}{SCREEN_CSS}</style></head>"
            f"<body><div class='page'>{body}</div></body></html>")


def title_of(text, fallback):
    for line in text.splitlines():
        line = line.strip().lstrip("#").strip().strip("*")
        if line and not line.startswith("|"):
            return line[:60]
    return fallback


def _md_runs(par, text):
    """**bold** and *italic* inside a Word paragraph."""
    for part in re.split(r"(\*\*[^*]+\*\*|\*[^*]+\*)", text):
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            par.add_run(part[2:-2]).bold = True
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            par.add_run(part[1:-1]).italic = True
        elif part:
            par.add_run(part)


def md_to_docx(text, path):
    from docx import Document
    from docx.shared import Pt, RGBColor, Mm
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Mm(210), Mm(297)
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(sec, side, Mm(18))
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(10.5)
    lines, i = text.splitlines(), 0
    while i < len(lines):
        line = lines[i].rstrip()
        if line.lstrip().startswith("|"):   # a Markdown table block
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                    rows.append(cells)
                i += 1
            if rows:
                n = max(len(r) for r in rows)
                t = doc.add_table(rows=len(rows), cols=n)
                t.style = "Light Grid Accent 1"
                for r, cells in enumerate(rows):
                    for c in range(n):
                        par = t.cell(r, c).paragraphs[0]
                        _md_runs(par, cells[c] if c < len(cells) else "")
                        if r == 0:
                            for run in par.runs:
                                run.bold = True
                doc.add_paragraph()
            continue
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            hashes = len(m.group(1))
            h = doc.add_heading(m.group(2).strip("* "), level=0 if hashes == 1 else min(hashes - 1, 3))
            for run in h.runs:
                run.font.color.rgb = RGBColor(0x1E, 0x3A, 0x6E)
        elif re.match(r"^\s*[-*+]\s+", line):
            _md_runs(doc.add_paragraph(style="List Bullet"), re.sub(r"^\s*[-*+]\s+", "", line))
        elif re.match(r"^\s*\d+[.)]\s+", line):
            _md_runs(doc.add_paragraph(style="List Number"), re.sub(r"^\s*\d+[.)]\s+", "", line))
        elif line.strip() in ("---", "***"):
            doc.add_paragraph("_" * 60)
        elif line.strip():
            _md_runs(doc.add_paragraph(), line.strip().lstrip(">").strip())
        i += 1
    doc.save(path)


def _num(v):
    try:
        f = float(v.replace(",", "").replace("$", "").strip())
        return int(f) if f.is_integer() and "." not in v else f
    except ValueError:
        return v


def csv_rows(text):
    rows = [r for r in csv.reader(io.StringIO(text.strip())) if any(c.strip() for c in r)]
    return [[_num(c.strip()) for c in r] for r in rows]


def csv_to_xlsx(rows, path, title):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    ws = wb.active
    ws.title = re.sub(r"[\\/*?:\[\]]", "", title)[:31] or "Sheet1"
    for r in rows:
        ws.append(r)
    head = PatternFill("solid", fgColor="1E3A6E")
    for c in ws[1]:
        c.font, c.fill, c.alignment = Font(bold=True, color="FFFFFF"), head, Alignment(vertical="center")
    if rows and str(rows[-1][0]).strip().lower().startswith("total"):
        for c in ws[ws.max_row]:
            c.font = Font(bold=True)
    for col in range(1, ws.max_column + 1):
        width = max(len(str(ws.cell(r, col).value or "")) for r in range(1, ws.max_row + 1))
        ws.column_dimensions[get_column_letter(col)].width = min(50, max(10, width + 2))
        for r in range(2, ws.max_row + 1):
            if isinstance(ws.cell(r, col).value, float):
                ws.cell(r, col).number_format = "#,##0.00"
    ws.freeze_panes = "A2"
    wb.save(path)


def rows_to_html(rows, title):
    def cell(v, tag):
        right = isinstance(v, (int, float))
        shown = f"{v:,.2f}" if isinstance(v, float) else (f"{v:,}" if isinstance(v, int) else html.escape(str(v)))
        return f"<{tag}{' class=n' if right else ''}>{shown}</{tag}>"
    head = "".join(cell(v, "th") for v in rows[0]) if rows else ""
    body = "".join("<tr><td class=rn>%d</td>%s</tr>" % (i + 2, "".join(cell(v, "td") for v in r)) for i, r in enumerate(rows[1:]))
    cols = "".join(f"<th class=cl>{chr(65 + i)}</th>" for i in range(len(rows[0]) if rows else 0))
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title><style>"
            "body{margin:0;font:13px -apple-system,Segoe UI,Arial,sans-serif;background:#fff;color:#111}"
            "table{border-collapse:collapse;min-width:100%}td,th{border:1px solid #d9dde3;padding:6px 10px;white-space:nowrap}"
            "th{background:#1e3a6e;color:#fff;text-align:left;position:sticky;top:26px}.cl{background:#f1f3f6;color:#666;"
            "font-weight:500;text-align:center;top:0}.rn{background:#f1f3f6;color:#666;text-align:center;width:36px}"
            ".n{text-align:right;font-variant-numeric:tabular-nums}tr:last-child td{font-weight:600}</style></head><body>"
            f"<table><tr><th class=cl></th>{cols}</tr><tr><td class=rn>1</td>{head}</tr>{body}</table></body></html>")


def md_slides(text):
    """'# Title / subtitle / ## Slide / - bullet' -> (title, subtitle, [(slide title, [bullets])])"""
    title, subtitle, slides = "", "", []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("## "):
            slides.append([s[3:].strip("* "), []])
        elif s.startswith("# ") and not title:
            title = s[2:].strip("* ")
        elif re.match(r"^[-*+]\s+|^\d+[.)]\s+", s) and slides:
            slides[-1][1].append(re.sub(r"^[-*+]\s+|^\d+[.)]\s+", "", s).replace("**", ""))
        elif not slides and not subtitle and title:
            subtitle = s.replace("**", "")
        elif slides:
            slides[-1][1].append(s.replace("**", ""))
    return title or "Presentation", subtitle, slides


def slides_to_pptx(title, subtitle, slides, path):
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.util import Inches, Pt
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    navy = RGBColor(0x1E, 0x3A, 0x6E)

    def bar(slide):
        shape = slide.shapes.add_shape(1, 0, 0, prs.slide_width, Inches(0.18))
        shape.fill.solid()
        shape.fill.fore_color.rgb = navy
        shape.line.fill.background()

    s = prs.slides.add_slide(prs.slide_layouts[0])
    s.shapes.title.text = title
    s.shapes.title.text_frame.paragraphs[0].font.color.rgb = navy
    s.shapes.title.text_frame.paragraphs[0].font.bold = True
    s.placeholders[1].text = subtitle
    bar(s)
    for head, bullets in slides:
        s = prs.slides.add_slide(prs.slide_layouts[1])
        s.shapes.title.text = head
        p0 = s.shapes.title.text_frame.paragraphs[0]
        p0.font.color.rgb, p0.font.bold, p0.font.size = navy, True, Pt(34)
        body = s.placeholders[1]
        body.left, body.top, body.width, body.height = Inches(0.8), Inches(1.7), Inches(11.7), Inches(5.2)
        tf = body.text_frame
        for j, b in enumerate(bullets or [""]):
            p = tf.paragraphs[0] if j == 0 else tf.add_paragraph()
            p.text = b
            p.font.size = Pt(22)
        bar(s)
    prs.save(path)


def slides_to_html(title, subtitle, slides):
    cards = [f"<section class='s first'><h1>{html.escape(title)}</h1><p>{html.escape(subtitle)}</p><i>1</i></section>"]
    for n, (head, bullets) in enumerate(slides, start=2):
        lis = "".join(f"<li>{html.escape(b)}</li>" for b in bullets)
        cards.append(f"<section class='s'><h2>{html.escape(head)}</h2><ul>{lis}</ul><i>{n}</i></section>")
    return ("<!doctype html><html><head><meta charset='utf-8'><title>%s</title><style>"
            "body{margin:0;background:#e9ecf1;font-family:-apple-system,Segoe UI,Arial,sans-serif;padding:20px;display:grid;gap:20px}"
            ".s{position:relative;aspect-ratio:16/9;background:#fff;border-top:8px solid #1e3a6e;box-shadow:0 2px 12px rgba(0,0,0,.12);"
            "padding:5%% 6%%;box-sizing:border-box;overflow:hidden;container-type:inline-size}"
            ".first{display:flex;flex-direction:column;justify-content:center}h1{color:#1e3a6e;font-size:6cqw;margin:0 0 2cqw}"
            "h2{color:#1e3a6e;font-size:4.2cqw;margin:0 0 3cqw}p{font-size:2.6cqw;color:#555;margin:0}"
            "ul{font-size:2.5cqw;line-height:1.5;color:#222;padding-left:4cqw}i{position:absolute;right:3cqw;bottom:2cqw;"
            "font-size:1.6cqw;color:#999;font-style:normal}</style></head><body>%s</body></html>") % (html.escape(title), "".join(cards))


def react_preview(code):
    """Runs the component in the browser: React + Babel from a CDN, imports/exports stripped."""
    body = re.sub(r"^\s*import\s[^;]*?from\s+['\"][^'\"]+['\"];?\s*$", "", code, flags=re.M)
    body = re.sub(r"^\s*import\s+['\"][^'\"]+['\"];?\s*$", "", body, flags=re.M)
    body = re.sub(r"export\s+default\s+function\s+(\w+)", r"function \1", body)
    name = (re.search(r"export\s+default\s+function\s+(\w+)", code) or re.search(r"export\s+default\s+(\w+)", code))
    name = name.group(1) if name else "App"
    body = re.sub(r"^\s*export\s+default\s+\w+;?\s*$", "", body, flags=re.M).replace("export function", "function")
    js = json.dumps(body + f"\n;ReactDOM.createRoot(document.getElementById('root')).render(React.createElement({name}));")
    return ("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<script src='https://unpkg.com/react@18.3.1/umd/react.development.js'></script>"
            "<script src='https://unpkg.com/react-dom@18.3.1/umd/react-dom.development.js'></script>"
            "<script src='https://unpkg.com/@babel/standalone@7.26.4/babel.min.js'></script>"
            "<style>body{margin:0;font-family:-apple-system,Segoe UI,Arial,sans-serif}#err{color:#b91c1c;white-space:pre-wrap;"
            "font:13px ui-monospace,monospace;padding:16px}</style></head><body><div id='root'></div><pre id='err'></pre><script>"
            "const {useState,useEffect,useRef,useMemo,useCallback,useReducer,useContext,createContext,Fragment}=React;"
            f"try{{const out=Babel.transform({js},{{presets:['react']}}).code;(0,eval)(out)}}"
            "catch(e){document.getElementById('err').textContent='Preview error: '+e.message}"
            "</script></body></html>")


def html_to_pdf(html_path, pdf_path):
    if not os.path.exists(CHROME):
        raise RuntimeError("PDF needs Google Chrome (set CHROME_BIN to its path).")
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--no-first-run",
                    f"--print-to-pdf={pdf_path}", "file://" + html_path], check=True, timeout=120,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not os.path.exists(pdf_path):
        raise RuntimeError("Chrome didn't produce the PDF.")


def slug(text):
    s = re.sub(r"[^\w\s-]", "", text, flags=re.U).strip().lower()
    return re.sub(r"[\s_-]+", "-", s)[:50] or "file"


FILLER = re.compile(r"\b(please|pls|can you|could you|help( me)?|create|creaet|make|write|generate|build|design|give me|now|"
                    r"use|using|with|in|as|a|an|the|for me|code|simple|reactjs|react|jsx|html|file|app)\b", re.I)


def short_title(ask):
    """'Please create POS system simple now use reactjs write code' -> 'POS System'"""
    words = FILLER.sub(" ", ask).split()
    return " ".join(w if w.isupper() else w.capitalize() for w in words[:5]) or "FongAI file"


def build_file(kind, source, fallback_title="FongAI file"):
    """Source text -> real file + preview. Returns the card info the UI shows."""
    meta = KINDS[kind]
    if kind in ("pdf", "docx", "pptx"):
        title = title_of(source, fallback_title)
    elif kind == "html":
        m = re.search(r"<title>(.*?)</title>", source, re.S | re.I)
        title = (m.group(1).strip() if m else "") or fallback_title
    else:
        m = re.search(r"<h1[^>]*>\s*([^<{]{3,60}?)\s*</h1>", source)
        title = m.group(1).strip() if m else short_title(fallback_title)
    folder = os.path.join(FILES_DIR, time.strftime("%Y%m%d_%H%M%S") + "_" + os.urandom(3).hex())
    os.makedirs(folder, exist_ok=True)
    name = f"{slug(title)}.{meta['ext']}"
    path = os.path.join(folder, name)
    preview = os.path.join(folder, "preview.html")
    if kind in ("pdf", "docx"):
        with open(preview, "w", encoding="utf-8") as f:
            f.write(md_to_html_page(source, title))
        if kind == "pdf":
            html_to_pdf(preview, path)
            preview = path   # the browser's own PDF viewer shows the real file
        else:
            md_to_docx(source, path)
    elif kind == "xlsx":
        rows = csv_rows(source)
        csv_to_xlsx(rows, path, title)
        with open(preview, "w", encoding="utf-8") as f:
            f.write(rows_to_html(rows, title))
    elif kind == "pptx":
        t, sub, slides = md_slides(source)
        slides_to_pptx(t, sub, slides, path)
        with open(preview, "w", encoding="utf-8") as f:
            f.write(slides_to_html(t, sub, slides))
    elif kind == "react":
        with open(path, "w", encoding="utf-8") as f:
            f.write(source + "\n")
        with open(preview, "w", encoding="utf-8") as f:
            f.write(react_preview(source))
    elif kind == "html":
        with open(path, "w", encoding="utf-8") as f:
            f.write(source)
        preview = path
    with open(os.path.join(folder, "source.txt"), "w", encoding="utf-8") as f:
        f.write(source)
    LAST.clear()
    LAST.update(kind=kind, source=source, title=title)
    rel = os.path.relpath(folder, FILES_DIR)
    return {"kind": kind, "name": name, "title": title, "label": meta["label"], "group": meta["group"],
            "url": f"/files/{rel}/{name}", "preview_url": f"/files/{rel}/{os.path.basename(preview)}",
            "code": source if kind in ("react", "html") else None, "size": os.path.getsize(path),
            "date": time.time()}
