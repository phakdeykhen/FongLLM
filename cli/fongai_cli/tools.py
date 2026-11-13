"""The tools the model can use. Pure Python so they work the same on macOS, Linux and Windows."""
import difflib
import fnmatch
import json
import os
import platform
import re
import subprocess

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", ".idea", ".mypy_cache"}
MAX_OUT = 20000   # characters of tool output sent back to the model


def _fn(name, desc, props, required):
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required}}}


SCHEMAS = [
    _fn("read_file", "Read a text file. Returns numbered lines.",
        {"path": {"type": "string", "description": "File path"},
         "offset": {"type": "integer", "description": "First line (1-based), optional"},
         "limit": {"type": "integer", "description": "Number of lines, optional"}}, ["path"]),
    _fn("write_file", "Create or overwrite a file with the given content.",
        {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
    _fn("edit_file", "Replace an exact piece of text in a file. old_text must appear exactly once.",
        {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}},
        ["path", "old_text", "new_text"]),
    _fn("list_files", "List files under a folder, optionally filtered by a glob like '*.py'.",
        {"path": {"type": "string", "description": "Folder, default '.'"},
         "pattern": {"type": "string", "description": "Glob, default '*'"}}, []),
    _fn("search", "Search file contents with a regular expression. Returns path:line: text.",
        {"pattern": {"type": "string"}, "path": {"type": "string", "description": "Folder, default '.'"},
         "glob": {"type": "string", "description": "Only files matching this glob, e.g. '*.js'"}}, ["pattern"]),
    _fn("run_command", f"Run a shell command in the project folder ({platform.system()} shell) and return its output. "
        "Use for tests, builds, git, installing packages.",
        {"command": {"type": "string"}, "timeout": {"type": "integer", "description": "Seconds, default 120"}},
        ["command"]),
]

NEEDS_OK = {"write_file", "edit_file", "run_command"}   # ask the user first unless --yes


def _clip(s):
    return s if len(s) <= MAX_OUT else s[:MAX_OUT] + f"\n... [cut, {len(s) - MAX_OUT} more characters]"


def _walk(root):
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS and not x.startswith("."))
        for f in sorted(files):
            yield os.path.join(d, f)


def read_file(path, offset=1, limit=None):
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    start = max(int(offset or 1), 1)
    end = len(lines) if not limit else min(len(lines), start - 1 + int(limit))
    if not lines:
        return "(empty file)"
    return _clip("\n".join(f"{i:>5}  {lines[i - 1]}" for i in range(start, end + 1)))


def write_file(path, content):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    return f"Wrote {path} ({content.count(chr(10)) + 1} lines)"


def edit_file(path, old_text, new_text):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    n = text.count(old_text)
    if n == 0:
        return "ERROR: old_text not found. Read the file again and copy the text exactly."
    if n > 1:
        return f"ERROR: old_text appears {n} times. Include more surrounding lines so it is unique."
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text.replace(old_text, new_text, 1))
    return f"Edited {path}"


def list_files(path=".", pattern="*"):
    out = [os.path.relpath(p, path) for p in _walk(path) if fnmatch.fnmatch(os.path.basename(p), pattern or "*")]
    return _clip("\n".join(out[:1000]) + (f"\n... {len(out) - 1000} more" if len(out) > 1000 else "")) or "(no files)"


def search(pattern, path=".", glob=None):
    rx = re.compile(pattern)
    hits = []
    for p in _walk(path):
        if glob and not fnmatch.fnmatch(os.path.basename(p), glob):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                for i, line in enumerate(f, 1):
                    if rx.search(line):
                        hits.append(f"{os.path.relpath(p, path)}:{i}: {line.rstrip()[:300]}")
                        if len(hits) >= 300:
                            return "\n".join(hits) + "\n... (stopped at 300 matches)"
        except (UnicodeDecodeError, OSError):
            continue
    return "\n".join(hits) or "(no matches)"


def run_command(command, timeout=120):
    try:
        r = subprocess.run(command, shell=True, capture_output=True, text=True,
                           timeout=int(timeout or 120), encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return f"ERROR: timed out after {timeout}s"
    out = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else "")
    return _clip(f"exit code {r.returncode}\n{out.strip()}")


FUNCS = {f.__name__: f for f in (read_file, write_file, edit_file, list_files, search, run_command)}


def preview(name, args):
    """Short human-readable description of a tool call, shown before asking permission."""
    if name == "run_command":
        return f"$ {args.get('command', '')}"
    if name == "write_file":
        new = args.get("content", "")
        old = ""
        if os.path.exists(args.get("path", "")):
            with open(args["path"], encoding="utf-8", errors="replace") as f:
                old = f.read()
        return f"write {args.get('path')}\n" + _diff(old, new, args.get("path", ""))
    if name == "edit_file":
        return f"edit {args.get('path')}\n" + _diff(args.get("old_text", ""), args.get("new_text", ""), args.get("path", ""))
    return f"{name} {json.dumps(args, ensure_ascii=False)[:200]}"


def _diff(a, b, name):
    d = list(difflib.unified_diff(a.splitlines(), b.splitlines(), name, name, lineterm="", n=2))
    s = "\n".join(d[2:]) if d else "(no change)"
    return s if len(s) < 4000 else s[:4000] + "\n..."


def call(name, raw_args):
    if name not in FUNCS:
        return f"ERROR: unknown tool {name}"
    try:
        args = json.loads(raw_args) if isinstance(raw_args, str) and raw_args.strip() else (raw_args or {})
    except json.JSONDecodeError as e:
        return f"ERROR: arguments are not valid JSON ({e})"
    try:
        return FUNCS[name](**args)
    except TypeError as e:
        return f"ERROR: bad arguments: {e}"
    except Exception as e:  # report to the model so it can recover
        return f"ERROR: {type(e).__name__}: {e}"
