"""FongAI public chat page (Hugging Face Spaces, free CPU)."""
import os
from threading import Thread

import gradio as gr
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, TextIteratorStreamer

MODEL = os.environ.get("FONGAI_MODEL", os.path.join(os.path.dirname(os.path.abspath(__file__)), "fongai-3"))
tok = AutoTokenizer.from_pretrained(MODEL)
model = AutoModelForCausalLM.from_pretrained(MODEL, dtype=torch.float32, attn_implementation="eager").eval()
torch.set_num_threads(max(1, os.cpu_count() or 1))


def chat(message, history):
    msgs = [{"role": m["role"], "content": m["content"]} for m in history[-6:] if isinstance(m.get("content"), str)]
    msgs.append({"role": "user", "content": message})
    ids = tok.apply_chat_template(msgs, add_generation_prompt=True, return_tensors="pt")[:, -1536:]
    streamer = TextIteratorStreamer(tok, skip_prompt=True, skip_special_tokens=True)
    Thread(target=model.generate, kwargs=dict(
        input_ids=ids, attention_mask=torch.ones_like(ids), streamer=streamer, max_new_tokens=400,
        do_sample=True, temperature=0.7, top_p=0.9, repetition_penalty=1.1,
        pad_token_id=tok.pad_token_id, eos_token_id=tok.eos_token_id)).start()
    reply = ""
    for piece in streamer:
        reply += piece
        yield reply


demo = gr.ChatInterface(
    chat,
    type="messages",
    title="FongAI",
    description="FongAI is a tiny (64M) AI assistant. It's fast and fun, but it often makes mistakes, so don't trust its facts.",
    examples=["Who are you?", "Give me a tip for sleeping better.", "Write a short poem about rain.", "你好，你是谁？"],
)

if __name__ == "__main__":
    demo.queue(default_concurrency_limit=4).launch()
