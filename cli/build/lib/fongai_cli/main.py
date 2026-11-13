"""fong: Fong AI coding assistant for the terminal.

  fong                      start a chat in the current folder
  fong "add tests for x"    do one task and exit
  fong --yes ...            don't ask before writing files or running commands

Settings (flags > environment > ~/.fongai/config.json > defaults):
  FONG_BASE_URL  default http://localhost:11434/v1   (Ollama; any OpenAI-compatible API works)
  FONG_MODEL     default fongai
  FONG_API_KEY   only needed for hosted APIs
"""
import argparse
import json
import os
import platform
import re
import sys

from . import __version__, tools
from .llm import LLMError, chat_stream

CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".fongai", "config.json")
DEFAULTS = {"base_url": "http://localhost:11434/v1", "model": "fongai", "api_key": ""}
MAX_STEPS = 40   # tool rounds per request, so a confused model can't loop forever

if os.name == "nt":
    os.system("")   # turn on ANSI colors in the Windows console
COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def c(code, s):
    return f"\033[{code}m{s}\033[0m" if COLOR else s


DIM, BOLD, RED, GREEN, YELLOW, CYAN = "2", "1", "31", "32", "33", "36"


def load_config(args):
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update({k: v for k, v in json.load(f).items() if v})
    except (OSError, json.JSONDecodeError):
        pass
    for key in cfg:
        env = os.environ.get("FONG_" + key.upper())
        if env:
            cfg[key] = env
        flag = getattr(args, key, None)
        if flag:
            cfg[key] = flag
    return cfg


def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def system_prompt():
    cwd = os.getcwd()
    s = (
        "You are Fong AI, a coding assistant working in the user's terminal.\n"
        f"Project folder: {cwd}\nOS: {platform.system()} {platform.release()}\n\n"
        "Do the task with your tools instead of only describing it:\n"
        "- Look before you change: use list_files, search and read_file to understand the code.\n"
        "- Change files with edit_file (small changes) or write_file (new files). Copy old_text exactly.\n"
        "- After changing code, run it or its tests with run_command and fix any errors.\n"
        "- Keep answers short. Answer in the user's language.\n"
        "- When done, say in one or two sentences what you changed."
    )
    for name in ("FONG.md", "AGENTS.md", "CLAUDE.md"):   # project instructions, if the repo has them
        p = os.path.join(cwd, name)
        if os.path.isfile(p):
            with open(p, encoding="utf-8", errors="replace") as f:
                s += f"\n\nProject instructions from {name}:\n{f.read()[:8000]}"
            break
    return s


TEXT_CALL = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


def calls_from_text(text):
    """Some local models write tool calls as text instead of using the API field. Recover them."""
    out = []
    for i, m in enumerate(TEXT_CALL.findall(text)):
        try:
            d = json.loads(m)
        except json.JSONDecodeError:
            continue
        if d.get("name") in tools.FUNCS:
            args = d.get("arguments", {})
            out.append({"id": f"text_{i}", "type": "function",
                        "function": {"name": d["name"], "arguments": args if isinstance(args, str) else json.dumps(args)}})
    return out


def ask(question):
    try:
        return input(question).strip().lower()
    except EOFError:
        return "n"


class Session:
    def __init__(self, cfg, auto_yes):
        self.cfg = cfg
        self.auto_yes = auto_yes
        self.messages = [{"role": "system", "content": system_prompt()}]

    def allowed(self, name, args):
        if self.auto_yes or name not in tools.NEEDS_OK:
            return True
        print(c(YELLOW, tools.preview(name, args)))
        a = ask(c(BOLD, "Allow? [y]es / [n]o / [a]lways this session: "))
        if a in ("a", "always"):
            self.auto_yes = True
            return True
        return a in ("y", "yes", "")

    def run(self, prompt):
        self.messages.append({"role": "user", "content": prompt})
        for _ in range(MAX_STEPS):
            started = [False]

            def on_text(d):
                if not started[0]:
                    started[0] = True
                print(d, end="", flush=True)

            try:
                text, calls = chat_stream(self.cfg["base_url"], self.cfg["api_key"], self.cfg["model"],
                                          self.messages, tools.SCHEMAS, on_text)
            except LLMError as e:
                print(c(RED, f"\n{e}"))
                self.messages.pop()
                return
            if started[0]:
                print()
            if not calls:
                calls = calls_from_text(text)
                if calls:
                    text = TEXT_CALL.sub("", text).strip()
            msg = {"role": "assistant", "content": text}
            if calls:
                msg["tool_calls"] = calls
            self.messages.append(msg)
            if not calls:
                return
            for call in calls:
                name, raw = call["function"]["name"], call["function"]["arguments"]
                try:
                    args = json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    args = {}
                label = args.get("path") or args.get("command") or args.get("pattern") or ""
                print(c(CYAN, f"● {name}") + c(DIM, f" {label}"[:120]))
                if self.allowed(name, args):
                    result = tools.call(name, raw)
                else:
                    result = "The user declined this action. Ask what they want instead."
                first = result.splitlines()[0] if result else ""
                print(c(RED if result.startswith("ERROR") else DIM, "  ⎿ " + first[:150]))
                self.messages.append({"role": "tool", "tool_call_id": call["id"], "name": name, "content": result})
        print(c(YELLOW, f"Stopped after {MAX_STEPS} steps. Say 'continue' to keep going."))


HELP = """Commands:
  /help            this help
  /model [name]    show or change the model (saved for next time)
  /url [base_url]  show or change the API address (saved)
  /yes             stop asking before edits and commands
  /clear           forget this conversation
  /exit            quit (or Ctrl+D)"""


def repl(session):
    cfg = session.cfg
    print(c(BOLD, f"Fong AI {__version__}") + c(DIM, f"  model {cfg['model']} · {os.getcwd()}"))
    print(c(DIM, "Ask anything about your code. /help for commands.\n"))
    try:
        import readline  # noqa: F401  (arrow keys and history on macOS/Linux)
    except ImportError:
        pass
    while True:
        try:
            line = input(c(GREEN, "› ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if line.startswith("/"):
            cmd, _, arg = line.partition(" ")
            arg = arg.strip()
            if cmd in ("/exit", "/quit"):
                return
            elif cmd == "/help":
                print(HELP)
            elif cmd == "/clear":
                session.messages = session.messages[:1]
                print(c(DIM, "Conversation cleared."))
            elif cmd == "/yes":
                session.auto_yes = True
                print(c(DIM, "Won't ask again this session."))
            elif cmd in ("/model", "/url"):
                key = "model" if cmd == "/model" else "base_url"
                if arg:
                    cfg[key] = arg
                    save_config(cfg)
                print(c(DIM, f"{key}: {cfg[key]}"))
            else:
                print(c(RED, f"Unknown command {cmd}. /help"))
            continue
        try:
            session.run(line)
        except KeyboardInterrupt:
            print(c(YELLOW, "\nInterrupted."))
            while session.messages[-1]["role"] != "user":   # drop the half-finished turn
                session.messages.pop()
            session.messages.pop()


def main():
    p = argparse.ArgumentParser(prog="fong", description="Fong AI coding assistant for the terminal.")
    p.add_argument("prompt", nargs="*", help="task to do, then exit (leave empty to chat)")
    p.add_argument("-m", "--model", help="model name (default fongai)")
    p.add_argument("--base-url", dest="base_url", help="OpenAI-compatible API address")
    p.add_argument("--api-key", dest="api_key", help="API key for hosted APIs")
    p.add_argument("-y", "--yes", action="store_true", help="don't ask before edits and commands")
    p.add_argument("-v", "--version", action="version", version=f"fong {__version__}")
    args = p.parse_args()
    session = Session(load_config(args), args.yes)
    if args.prompt:
        try:
            session.run(" ".join(args.prompt))
        except KeyboardInterrupt:
            print(c(YELLOW, "\nInterrupted."))
            sys.exit(130)
    else:
        repl(session)


if __name__ == "__main__":
    main()
