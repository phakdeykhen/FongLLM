"""Identity fine-tune: teach the ready-made minimind-3 model that its name is FongAI.
Run: cd ~/Documents/FongAI && .venv/bin/python trainer/train_identity.py
Writes assistant/models/fongai-3 (original minimind-3 is left untouched)."""
import json, os, random, re, shutil, time, torch
from transformers import AutoModelForCausalLM, AutoTokenizer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC, DST = f"{ROOT}/assistant/models/minimind-3", f"{ROOT}/assistant/models/fongai-3"
DEV = "mps" if torch.backends.mps.is_available() else "cpu"
random.seed(0); torch.manual_seed(0)

en_q = ["Who are you?", "What is your name?", "What's your name?", "Introduce yourself.", "Are you Qwen?",
        "Are you ChatGPT?", "Who made you?", "Who created you?", "What model are you?", "Tell me about yourself.",
        "What should I call you?", "Are you MiniMind?", "Hi! Who am I talking to?", "Which AI are you?",
        "What are you?", "Who built you?", "Are you made by Alibaba?", "What is your identity?"]
en_a = ["I am FongAI, a small and efficient AI assistant. How can I help you today?",
        "My name is FongAI. I'm a lightweight AI assistant here to answer your questions.",
        "I'm FongAI, a compact AI assistant that runs locally on your computer. What can I do for you?",
        "I am FongAI. I'm not Qwen or ChatGPT; I'm FongAI, your own local AI assistant.",
        "You can call me FongAI. I'm a small AI assistant built to help with questions, writing and ideas."]
zh_q = ["你是谁？", "你叫什么名字？", "介绍一下你自己。", "你是通义千问吗？", "你是ChatGPT吗？", "谁开发了你？",
        "你是哪个模型？", "我该怎么称呼你？", "你是MiniMind吗？", "你好，你是谁呀？", "你是由谁创建的？", "你背后的模型是哪个？"]
zh_a = ["我是FongAI，一个高效的小型AI助手。有什么可以帮你的吗？",
        "我叫FongAI，是一个运行在你电脑上的轻量级AI助手。",
        "你好！我是FongAI，很高兴为你提供帮助。",
        "我是FongAI，不是通义千问，也不是ChatGPT。我是你的本地AI助手FongAI。"]
km_q = ["អ្នកជានរណា?", "តើអ្នកឈ្មោះអ្វី?", "សូមណែនាំខ្លួនអ្នក។", "ខ្ញុំគួរហៅអ្នកថាអ្វី?"]
km_a = ["ខ្ញុំគឺ FongAI ជាជំនួយការ AI តូចមួយ។ តើខ្ញុំអាចជួយអ្វីបាន?",
        "ខ្ញុំឈ្មោះ FongAI។ ខ្ញុំជាជំនួយការ AI ដែលដំណើរការនៅលើកុំព្យូទ័ររបស់អ្នក។"]
# Khmer is left out: the base model cannot write Khmer, so it only learns garbage there.
ident = [(q, random.choice(a)) for qs, a in [(en_q, en_a), (zh_q, zh_a)] for q in qs]

BAD = re.compile(r"jingyaogong|minimind|qwen|通义|阿里|千问|openai|chatgpt", re.I)
replay = []
with open(f"{ROOT}/dataset/sft_t2t_mini.jsonl") as f:
    for line in f:
        c = json.loads(line)["conversations"]
        if len(c) >= 2 and c[0]["role"] == "user" and c[1]["role"] == "assistant" and not BAD.search(c[0]["content"] + c[1]["content"]) \
                and len(c[0]["content"]) + len(c[1]["content"]) < 600:
            replay.append((c[0]["content"], c[1]["content"]))
        if len(replay) >= 4000:
            break
data = [("id", q, a) for q, a in ident] + [("gen", q, a) for q, a in replay]
print(f"identity examples: {len(ident)}, general replay: {len(replay)}, device: {DEV}")

tok = AutoTokenizer.from_pretrained(SRC)
model = AutoModelForCausalLM.from_pretrained(SRC, dtype=torch.float32, attn_implementation="eager").to(DEV)

def encode(q, a):
    p = tok.apply_chat_template([{"role": "user", "content": q}], tokenize=False, add_generation_prompt=True)
    full = tok.apply_chat_template([{"role": "user", "content": q}, {"role": "assistant", "content": a}], tokenize=False)
    pi, fi = tok(p)["input_ids"], tok(full)["input_ids"][:384]
    return fi, [-100] * len(pi) + fi[len(pi):]

def ask(q, n=60):
    ids = tok.apply_chat_template([{"role": "user", "content": q}], add_generation_prompt=True, return_tensors="pt").to(DEV)
    out = model.generate(ids, max_new_tokens=n, do_sample=False, pad_token_id=tok.pad_token_id, eos_token_id=tok.eos_token_id)
    return tok.decode(out[0][ids.shape[1]:], skip_special_tokens=True).strip().replace("\n", " ")[:120]

CHECK = ["Who are you?", "What is your name?", "你是谁？", "Who made you?", "What is the capital of France?", "What is 12 + 7?",
         "Write one sentence about the ocean.", "中国的首都是哪里？", "Give me a tip for sleeping better.", "Can you help me write an email?"]
model.eval(); print("\n--- BEFORE ---"); [print(f"{q} -> {ask(q)}") for q in CHECK]

enc = [encode(q, a) for _, q, a in data]
opt = torch.optim.AdamW(model.parameters(), lr=1.5e-5, weight_decay=0.01)
EPOCHS, BS = 1, 8
steps, t0 = EPOCHS * ((len(enc) + BS - 1) // BS), time.time()
sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=1.5e-5, total_steps=steps, pct_start=0.1)
pad = tok.pad_token_id if tok.pad_token_id is not None else 0
# Score = identity answers say FongAI AND normal answers stay normal (no FongAI leak, facts kept).
TESTS = [("Who are you?", "FongAI", True), ("What is your name?", "FongAI", True), ("你是谁？", "FongAI", True),
         ("Who made you?", "FongAI", True), ("What is the capital of France?", "Paris", True),
         ("Write one sentence about the ocean.", "FongAI", False), ("Can you help me write an email?", "FongAI", False),
         ("Give me a tip for sleeping better.", "FongAI", False), ("Write a short poem about rain.", "FongAI", False),
         ("What is the capital of Japan?", "Tokyo", True)]
def score():
    model.eval(); got = []
    for q, word, want in TESTS:
        got.append((word.lower() in ask(q, 40).lower()) == want)
    model.train(); return sum(got), "".join("✓" if g else "✗" for g in got)
best = (-1, 0, None)
model.train(); step = 0
for ep in range(EPOCHS):
    random.shuffle(enc)
    for i in range(0, len(enc), BS):
        b = enc[i:i + BS]; L = max(len(x) for x, _ in b)
        ids = torch.tensor([x + [pad] * (L - len(x)) for x, _ in b], device=DEV)
        lab = torch.tensor([y + [-100] * (L - len(y)) for _, y in b], device=DEV)
        att = torch.tensor([[1] * len(x) + [0] * (L - len(x)) for x, _ in b], device=DEV)
        loss = model(input_ids=ids, attention_mask=att, labels=lab).loss
        loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step(); sched.step(); opt.zero_grad(); step += 1
        if step % 75 == 0 or step == steps:
            sc, detail = score()
            print(f"step {step}/{steps} loss {loss.item():.3f} score {sc}/{len(TESTS)} {detail} ({time.time() - t0:.0f}s)", flush=True)
            if sc > best[0]:
                best = (sc, step, {k: v.detach().to("cpu", copy=True) for k, v in model.state_dict().items()})

print(f"\nBest: score {best[0]}/{len(TESTS)} at step {best[1]}"); model.load_state_dict(best[2])
model.eval(); print("\n--- AFTER ---"); [print(f"{q} -> {ask(q)}") for q in CHECK]
shutil.copytree(SRC, DST, dirs_exist_ok=True, ignore=shutil.ignore_patterns("model.safetensors", "images", "README*", "*.modelfile", ".msc", "._____temp"))
model.to(torch.float16).save_pretrained(DST); tok.save_pretrained(DST)
print(f"\nSaved to {DST} in {time.time() - t0:.0f}s")
