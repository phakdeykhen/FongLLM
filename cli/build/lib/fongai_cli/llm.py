"""Talks to any OpenAI-compatible chat API (Ollama by default) with streaming and tool calls."""
import json
import urllib.error
import urllib.request


class LLMError(Exception):
    pass


def chat_stream(base_url, api_key, model, messages, tools, on_text, temperature=0.2, timeout=600):
    """Stream one assistant turn. Calls on_text(delta) for answer text.

    Returns (text, tool_calls) where tool_calls is a list of
    {"id", "type": "function", "function": {"name", "arguments"}}.
    """
    body = {"model": model, "messages": messages, "stream": True, "temperature": temperature}
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key or 'none'}"},
    )
    text, calls = [], {}
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if chunk.get("error"):
                    raise LLMError(str(chunk["error"]))
                for choice in chunk.get("choices", []):
                    delta = choice.get("delta") or {}
                    if delta.get("content"):
                        text.append(delta["content"])
                        on_text(delta["content"])
                    for tc in delta.get("tool_calls") or []:
                        slot = calls.setdefault(tc.get("index", len(calls)),
                                                {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        slot["function"]["name"] += fn.get("name") or ""
                        args = fn.get("arguments")
                        if isinstance(args, dict):   # some servers send parsed JSON
                            args = json.dumps(args)
                        slot["function"]["arguments"] += args or ""
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        raise LLMError(f"HTTP {e.code} from {base_url}: {detail}") from None
    except urllib.error.URLError as e:
        raise LLMError(f"Cannot reach {base_url} ({e.reason}). Is the model server running?") from None
    tool_calls = [calls[k] for k in sorted(calls)]
    for i, c in enumerate(tool_calls):
        c["id"] = c["id"] or f"call_{i}"
    return "".join(text), tool_calls
