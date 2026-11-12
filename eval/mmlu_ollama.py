"""Quick MMLU score for an Ollama model (zero-shot, answer with one letter).

Run:  .venv/bin/python eval/mmlu_ollama.py [model] [questions_per_subject]
      e.g. .venv/bin/python eval/mmlu_ollama.py fongai 20
Writes eval/mmlu_<model>.json and prints overall accuracy and progress.
Note: published scores (Qwen 2.5 7B ~74, GPT-3.5 Turbo ~70) use 5-shot; this zero-shot check is close but not identical.
"""
import json, os, re, sys, time
import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = sys.argv[1] if len(sys.argv) > 1 else "fongai"
PER = int(sys.argv[2]) if len(sys.argv) > 2 else 20
OLLAMA = "http://localhost:11434/api/chat"

df = pd.read_parquet(os.path.join(HERE, "mmlu", "all", "test-00000-of-00001.parquet"))
df = df.groupby("subject", group_keys=False).apply(lambda g: g.head(PER)).reset_index(drop=True)
L = "ABCD"


def ask(row):
    q = (f"The following is a multiple choice question about {row.subject.replace('_', ' ')}.\n\n{row.question}\n"
         + "".join(f"{L[i]}. {c}\n" for i, c in enumerate(row.choices))
         + "\nAnswer with only the letter (A, B, C or D).")
    r = requests.post(OLLAMA, json={"model": MODEL, "stream": False, "options": {"temperature": 0, "num_predict": 4},
                                    "messages": [{"role": "user", "content": q}]}, timeout=300).json()
    m = re.search(r"\b([ABCD])\b", r["message"]["content"].strip().upper())
    return m.group(1) if m else "?"


right, rows, t0 = 0, [], time.time()
for i, row in enumerate(df.itertuples(), 1):
    got = ask(row)
    ok = got == L[row.answer]
    right += ok
    rows.append({"subject": row.subject, "got": got, "want": L[row.answer], "ok": ok})
    if i % 50 == 0 or i == len(df):
        print(f"[{i}/{len(df)}] accuracy so far {100 * right / i:.1f}%  ({time.time() - t0:.0f}s)", flush=True)

by = pd.DataFrame(rows).groupby("subject").ok.mean().sort_values()
out = {"model": MODEL, "questions": len(df), "per_subject": PER, "accuracy": round(100 * right / len(df), 1),
       "weakest": {k: round(100 * v) for k, v in by.head(5).items()}, "strongest": {k: round(100 * v) for k, v in by.tail(5).items()}}
json.dump(out, open(os.path.join(HERE, f"mmlu_{MODEL.replace(':', '_')}.json"), "w"), indent=2)
print(json.dumps(out, indent=2))
