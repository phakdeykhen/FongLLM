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
    ("pptx", r"\b(power ?points?|pptx?|slides?|slide ?decks?|decks?|presentations?|google ?slides?)\b"),
    ("xlsx", r"\b(excel|xlsx|spread ?sheets?|worksheets?|csv|google ?sheets?|g-?sheets?)\b"),
    ("docx", r"\b(docx|ms ?word|microsoft word|microsoft|word (document|doc|file|format)s?|(in|as|to) word|google ?docs?)\b"),
    ("react", r"\b(react(js)?|jsx|tsx|react component)\b"),
    ("html", r"\b(html|web ?page|website|landing ?page)\b"),
]
MAKE = re.compile(r"\b(creae?te?|creaet|make|write|generate|build|design|draft|prepare|produce|give me|export|save|"
                  r"convert|turn|put|need|want|do)\b|\bas (an? )?\w+ file\b|បង្កើត|ធ្វើ|做|生成|写", re.I)
PICTURE = re.compile(r"\b(png|jpe?g|logo|icon|picture|image|photo|poster|drawing|wallpaper|banner)s?\b", re.I)
GOOGLE_ASK = re.compile(r"\bgoogle ?(sheets?|docs?|slides?|drive)\b|\bg-?sheets?\b", re.I)
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
              "Import hooks from 'react' (useState, useEffect, ...). For icons import from 'lucide-react' "
              "(e.g. import { Users, Briefcase, Search, Bell, Settings, ChevronRight } from 'lucide-react'; use <Users size={20} />). "
              "NEVER use emoji anywhere: always a lucide icon instead. No other libraries, no CSS files: put styles in ONE "
              "<style>{`...`}</style> block or inline style objects; keep CSS short. Use realistic sample data in arrays. "
              "Keep the whole file under 300 lines and make sure it is COMPLETE: every tag, brace and function closed, "
              "ending with the closing of App. Make it look modern and polished. Output ONLY the code."),
    "html": ("Write ONE complete self-contained HTML file for the request below, with any extra CSS in a <style> tag and any "
             "JS in a <script> tag. Make it modern, polished and responsive. NEVER use emoji: for icons write <i data-lucide=\"name\"></i> "
             "with a Lucide icon name (users, briefcase, search, mail, phone, star, check, rocket, ...); the icon script is added for you. "
             "Output ONLY the HTML.\n\n"
             "A design kit stylesheet is added for you automatically: do NOT link any stylesheet and do NOT write CSS for the "
             "classes below (they are already styled); only set the brand color. For websites and landing pages, build "
             "the page from these classes so it looks professional:\n"
             "- <nav class=\"nav\"><div class=\"container\"><a class=\"logo\">Name</a><div class=\"links\"><a href=\"#about\">About</a>"
             "...<a class=\"btn\">Contact</a></div></div></nav>\n"
             "- <header class=\"hero\"><div class=\"container hero-grid\"><div><span class=\"eyebrow\">...</span><h1>...</h1>"
             "<p class=\"lead\">...</p><a class=\"btn\">...</a> <a class=\"btn btn-outline\">...</a></div><img class=\"hero-img\" "
             "src=\"...\"></div></header>\n"
             "- <section class=\"section\" id=\"...\"><div class=\"container\"><span class=\"eyebrow\">...</span><h2>...</h2>"
             "<p class=\"lead\">...</p><div class=\"grid\"><div class=\"card\"><div class=\"icon\"><i data-lucide=\"rocket\"></i></div><h3>...</h3><p>...</p></div>"
             "...</div></div></section>  (use class=\"section section-alt\" on every other section)\n"
             "- numbers: <div class=\"stats\"><div class=\"stat\"><b>15+</b><span>Years</span></div>...</div>\n"
             "- team: <div class=\"grid\"><div class=\"card person\"><img src=\"...\"><h3>Name</h3><p>Role</p></div>...</div>\n"
             "- quotes: <div class=\"card quote\"><p>\"...\"</p><cite>Name, Company</cite></div>\n"
             "- contact: <section class=\"section\" id=\"contact\"><div class=\"container contact-grid\"><div><h2>...</h2>"
             "<ul class=\"contact-list\"><li><b>Address</b>...</li><li><b>Phone</b>...</li><li><b>Email</b>...</li></ul></div>"
             "<form><input placeholder=\"Your name\"><input placeholder=\"Email\"><textarea rows=\"5\" placeholder=\"Message\">"
             "</textarea><button class=\"btn\">Send message</button></form></div></section>\n"
             "- <section class=\"cta\"><div class=\"container\"><h2>...</h2><p>...</p><a class=\"btn btn-light\">...</a></div></section>\n"
             "- <footer class=\"footer\"><div class=\"container\">...</div></footer>\n"
             "Rules: write REAL, specific content (invent a believable company name, services, numbers, people and contact "
             "details if none are given; never 'Company Name', 'Lorem ipsum' or 'Service 1'). A company website needs: nav, hero, "
             "about with stats, 3-6 services as cards, why-us, team (3-4 people), 2-3 testimonials, contact (address, phone, "
             "email, a form) and footer. Photos: https://picsum.photos/seed/WORD/900/650 (one different WORD per photo). "
             "Team photos: https://i.pravatar.cc/300?img=N (N from 1 to 70). Set the brand color with "
             "<style>:root{--brand:#2563eb}</style> (pick a color that fits the business)."),
}
# The kit the model builds on: good-looking defaults even when a small model writes little CSS of its own.
KIT_CSS = """
:where(:root){--brand:#2563eb;--ink:#0f172a;--muted:#64748b;--line:#e2e8f0;--soft:#f8fafc;--radius:16px}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;font:16px/1.65 Inter,system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans Khmer",sans-serif;color:var(--ink);background:#fff}
img{max-width:100%;display:block}a{color:var(--brand)}
h1,h2,h3{line-height:1.2;margin:0 0 .5em;letter-spacing:-.02em}
h1{font-size:clamp(2.2rem,5vw,3.6rem)}h2{font-size:clamp(1.7rem,3.5vw,2.5rem)}h3{font-size:1.2rem}
.container{width:min(1140px,100% - 40px);margin-inline:auto}
.nav{position:sticky;top:0;z-index:50;background:rgba(255,255,255,.85);backdrop-filter:blur(12px);border-bottom:1px solid var(--line)}
.nav .container{display:flex;align-items:center;justify-content:space-between;min-height:68px;gap:16px;flex-wrap:wrap}
.nav .logo{font-weight:800;font-size:1.3rem;color:var(--ink);text-decoration:none}
.nav .links{display:flex;gap:22px;align-items:center;flex-wrap:wrap}
.nav .links a:not(.btn){color:var(--ink);text-decoration:none;font-weight:500;opacity:.8}.nav .links a:hover{opacity:1;color:var(--brand)}
.btn{display:inline-block;padding:12px 24px;border-radius:999px;background:var(--brand);color:#fff!important;text-decoration:none;
 font-weight:600;border:2px solid var(--brand);cursor:pointer;transition:transform .15s,box-shadow .15s}
.btn:hover{transform:translateY(-2px);box-shadow:0 10px 24px -8px var(--brand)}
.btn-outline{background:transparent;color:var(--brand)!important}.btn.btn-light,.cta .btn{background:#fff;color:var(--brand)!important;border-color:#fff}
.hero{color:var(--ink);padding:clamp(56px,9vw,110px) 0;background:radial-gradient(1200px 500px at 85% -10%,color-mix(in srgb,var(--brand) 16%,transparent),transparent),var(--soft)}
.hero-grid{display:grid;grid-template-columns:1.1fr 1fr;gap:48px;align-items:center}
.hero-img{width:100%;aspect-ratio:4/3;object-fit:cover;border-radius:24px;box-shadow:0 30px 60px -20px rgba(15,23,42,.35)}
.eyebrow{display:inline-block;font-size:.8rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--brand);
 background:color-mix(in srgb,var(--brand) 10%,transparent);padding:6px 12px;border-radius:999px;margin-bottom:14px}
.lead{font-size:1.15rem;color:var(--muted);max-width:640px;margin:0 0 28px}
.section{padding:clamp(56px,8vw,96px) 0}.section-alt{background:var(--soft)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:24px;margin-top:32px}
.card{background:#fff;border:1px solid var(--line);border-radius:var(--radius);padding:28px;transition:transform .2s,box-shadow .2s}
.card:hover{transform:translateY(-4px);box-shadow:0 20px 40px -20px rgba(15,23,42,.25)}
.card p{color:var(--muted);margin:0}
.card .icon{width:52px;height:52px;display:grid;place-items:center;font-size:1.6rem;border-radius:14px;margin-bottom:16px;
 background:color-mix(in srgb,var(--brand) 12%,transparent)}
.person{text-align:center}.person img{width:120px;height:120px;border-radius:50%;object-fit:cover;margin:0 auto 16px}
.quote p{font-size:1.05rem;color:var(--ink);font-style:italic;margin-bottom:16px}.quote cite{color:var(--muted);font-style:normal;font-weight:600}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:20px;margin-top:32px}
.stat{padding:24px;border-radius:var(--radius);background:#fff;border:1px solid var(--line);text-align:center}
.stat b{display:block;font-size:2.2rem;color:var(--brand);line-height:1.1}.stat span{color:var(--muted)}
.cta{padding:72px 0;text-align:center;color:#fff;background:linear-gradient(135deg,var(--brand),color-mix(in srgb,var(--brand) 55%,#000))}
.cta h2{color:#fff}.cta p{opacity:.9;margin:0 auto 24px;max-width:600px}
.contact-grid{display:grid;grid-template-columns:1fr 1.2fr;gap:40px;align-items:start}
.contact-list{list-style:none;padding:0;margin:24px 0 0;display:grid;gap:14px}.contact-list li{color:var(--muted)}
.contact-list b{color:var(--ink);display:block}
form{display:grid;gap:14px;background:#fff;border:1px solid var(--line);border-radius:var(--radius);padding:28px}input,textarea,select{width:100%;padding:12px 14px;border:1px solid var(--line);border-radius:12px;font:inherit;background:#fff}
input:focus,textarea:focus{outline:2px solid var(--brand);border-color:transparent}
.footer{background:var(--ink);color:#cbd5e1;padding:48px 0;font-size:.95rem}.footer a{color:#fff}
@media (max-width:820px){.hero-grid,.contact-grid{grid-template-columns:1fr}.nav .links{gap:14px}}
"""


# a photo that can't load (offline, blocked host) becomes a soft brand-colored panel instead of a broken-image icon
KIT_JS = ("<script>addEventListener('error',function(e){var i=e.target;if(i.tagName!=='IMG'||i.dataset.kitFail)return;"
          "i.dataset.kitFail=1;i.alt='';i.src='data:image/svg+xml,'+encodeURIComponent(\"<svg xmlns='http://www.w3.org/2000/svg' "
          "width='900' height='650'><defs><linearGradient id='g' x2='1' y2='1'><stop stop-color='#2563eb'/><stop offset='1' "
          "stop-color='#93c5fd'/></linearGradient></defs><rect width='100%' height='100%' fill='url(%23g)'/></svg>\")},true)</script>")
LUCIDE_JS = ("<script src='https://unpkg.com/lucide@0.468.0/dist/umd/lucide.min.js'></script>"
             "<script>window.lucide&&lucide.createIcons()</script>")
KIT_PAGE = re.compile(r"class=[\"'][^\"']*\b(hero|nav|section|card)\b", re.I)


CONTACT_SECTION = """
<section class="section" id="contact"><div class="container contact-grid"><div><span class="eyebrow">Contact</span>
<h2>Let's talk</h2><p class="lead">Tell us about your project and we'll get back to you within one business day.</p></div>
<form onsubmit="event.preventDefault();this.querySelector('button').textContent='Thanks! We will be in touch.'">
<input required placeholder="Your name"><input required type="email" placeholder="Email"><textarea rows="5" placeholder="Message"></textarea>
<button class="btn">Send message</button></form></div></section>
"""


def with_contact(page):
    """A small model often forgets the contact section: a website built from the kit always gets one."""
    if not KIT_PAGE.search(page) or re.search(r"<form|id=[\"']contact[\"']", page, re.I):
        return page
    m = re.search(r"<section[^>]*class=[\"']cta|<footer", page, re.I) or re.search(r"</body>", page, re.I)
    return page[:m.start()] + CONTACT_SECTION + page[m.start():] if m else page


def with_kit(page):
    """Adds the kit stylesheet. On a page built from the kit's classes it goes last, so a small model's weaker rules for
    .btn/.card/... can't undo it (its own --brand color still applies); on any other page (a game, a tool) it goes
    first, so the page's own CSS wins."""
    page = re.sub(r"<link[^>]+href=[\"'][^\"']*(design-?kit|kit\.css)[^\"']*[\"'][^>]*>\s*", "", page, flags=re.I)
    tag = f"<style>{KIT_CSS}</style>{KIT_JS}"
    if "data-lucide" in page and "lucide.createIcons" not in page:
        page = re.sub(r"</body>", lambda m: LUCIDE_JS + m.group(0), page, count=1, flags=re.I) if re.search(r"</body>", page, re.I) else page + LUCIDE_JS
    if KIT_PAGE.search(page) and re.search(r"</head>", page, re.I):
        return re.sub(r"</head>", lambda m: tag + m.group(0), page, count=1, flags=re.I)
    if re.search(r"<head[^>]*>", page, re.I):
        return re.sub(r"(<head[^>]*>)", lambda m: m.group(1) + tag, page, count=1, flags=re.I)
    return tag + page
REVISE = ("Here is the current {label} source, between <<< and >>>:\n<<<\n{source}\n>>>\n\nApply the user's change below and "
          "output the FULL updated source in exactly the same format. Change only what the user asks. Output ONLY the source.")


def strip_fences(text):
    m = re.search(r"```[\w+-]*\n(.*?)```", text, re.S)
    text = (m.group(1) if m else text).strip()
    text = re.sub(r"^```[\w+-]*\s*\n", "", text)   # opening fence never closed (the reply was cut off)
    text = re.sub(r"\n```\s*$", "", text)
    # when updating a file the model sometimes copies the <<< >>> markers that wrapped the old version
    return re.sub(r"^\s*(<<<|>>>)\s*$\n?", "", text, flags=re.M).strip()


FIX = ("This {label} code does not work. Problem: {error}\n\nThe code, between <<< and >>>:\n<<<\n{source}\n>>>\n\n"
       "Output the FULL corrected file, complete from the first import to the last closing brace. Keep the same features "
       "and design. {extra}Output ONLY the code.")


def write_source(kind, ask, ollama_url, model, history=(), revise=False, on_progress=None, context="", fix=None):
    """Asks the Ollama model for the file's source text. on_progress(words, text_so_far) is called while it writes.
    context: passages from the user's uploaded documents. fix: (broken_source, error) to repair."""
    import requests
    if fix:
        src, error = fix
        cut = "cut off" in error
        user = FIX.format(label=KINDS[kind]["label"], error=error, source=src[-6000:] if cut else src,
                          extra=("It was cut off because it was too long: rewrite the WHOLE file shorter (under 250 lines, "
                                 "less CSS, fewer sections) so it finishes. " if cut else "")
                          + ("Icons come from 'lucide-react' or <i data-lucide>; never emoji. "))
        if cut:
            user += "\n\nOriginal request: " + ask
    elif revise and LAST:
        user = REVISE.format(label=KINDS[kind]["label"], source=LAST["source"]) + "\n\nUser's change: " + ask
    else:
        user = PROMPTS[kind] + "\n\nRequest: " + ask
    if context and not fix:
        user += ("\n\nThe user uploaded these requirement documents. Build what they describe (features, modules, "
                 "names, fields, wording):\n" + context)
    code = kind in ("react", "html")
    msgs = [{"role": "system", "content": "You are Fong AI. You write files exactly in the format asked, nothing else."}]
    msgs += [m for m in history if m["role"] == "user"][-2:] + [{"role": "user", "content": user}]
    r = requests.post(f"{ollama_url}/api/chat", stream=True, timeout=900, json={
        "model": model, "messages": msgs, "stream": True,
        **({"think": False} if model.startswith("fong-code") else {}),   # Bonsai 2: skip the long hidden reasoning
        "options": {"temperature": 0.3, "num_predict": 7000 if code else 4096, "num_ctx": 12288 if code else 8192}})
    r.raise_for_status()
    out, last = "", 0
    for line in r.iter_lines():
        if line:
            out += json.loads(line).get("message", {}).get("content", "")
            if on_progress and time.time() - last > 0.7:
                last = time.time()
                on_progress(len(out.split()), out)
    return strip_fences(out)


# ---------- checking generated code before the user sees it ----------
ESBUILD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "node_modules", ".bin", "esbuild")
EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF\U0001F900-\U0001F9FF\u2B50\u2B06\u2194-\u21AA]")


def check_source(kind, src):
    """None if the code looks good, else a short problem description the model can fix."""
    import subprocess
    if kind == "react":
        if os.path.exists(ESBUILD):
            r = subprocess.run([ESBUILD, "--loader=jsx", "--log-level=error", "--color=false"], input=src,
                               capture_output=True, text=True, timeout=30)
            if r.returncode:
                err = re.sub(r"\s+", " ", r.stderr).strip()[:600]
                end = re.search(r"Unexpected end of file|Expected .* but found end of file", err)
                return ("The file was cut off before the end. " if end else "Syntax error: ") + err
        if not re.search(r"export\s+default", src):
            return "There is no `export default function App()`."
    elif kind == "html":
        if not re.search(r"</html>\s*$", src, re.I):
            return "The file was cut off before </html>."
    if kind in ("react", "html"):
        found = sorted(set(EMOJI.findall(src)))
        if found:
            return "It uses emoji (" + " ".join(found[:8]) + "). Replace every emoji with a Lucide icon."
    return None


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
    def lucide(m):
        names = [n.strip().split(" as ") for n in m.group(1).split(",") if n.strip()]
        return "".join(f"const {(n[-1]).strip()}=LucideReact['{n[0].strip()}']||LucideReact.Circle;" for n in names)
    code = re.sub(r"^\s*import\s*\{([^}]*)\}\s*from\s*['\"]lucide-react['\"];?\s*$", lucide, code, flags=re.M)
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
            "<script>window.react=window.React</script>"
            "<script src='https://unpkg.com/lucide-react@0.468.0/dist/umd/lucide-react.min.js'></script>"
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
                    r"use|using|with|in|as|a|an|the|for me|code|simple|reactjs|react|jsx|html|file|app|"
                    r"i need|i want|need|want|do|same|just|my|our|for|of|to|google ?sheets?|g-?sheets?|sheets?|"
                    r"spread ?sheets?|excel|xlsx|csv|google ?docs?|google ?slides?|google ?drive|google)\b", re.I)


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
        source = with_contact(source)
        with open(path, "w", encoding="utf-8") as f:
            f.write(with_kit(source))
        preview = path
    with open(os.path.join(folder, "source.txt"), "w", encoding="utf-8") as f:
        f.write(source)
    LAST.clear()
    LAST.update(kind=kind, source=source, title=title)
    rel = os.path.relpath(folder, FILES_DIR)
    return {"kind": kind, "name": name, "title": title, "label": meta["label"], "group": meta["group"],
            "url": f"/files/{rel}/{name}", "preview_url": f"/files/{rel}/{os.path.basename(preview)}",
            "code": with_kit(source) if kind == "html" else source if kind == "react" else None, "size": os.path.getsize(path),
            "date": time.time()}
