"""Generate with the merged fine-tuned writer via transformers on CPU (used because the GGUF conversion was not allowed).
Run with the temp venv: python p8_hf_generate.py MODEL_DIR IN.jsonl OUT.jsonl   (IN rows: {key, messages, seed})"""
import json
import sys
import time

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

mdir, inp, outp = sys.argv[1:4]
tok = AutoTokenizer.from_pretrained(mdir)
model = AutoModelForCausalLM.from_pretrained(mdir, dtype=torch.float32).eval()
torch.set_num_threads(8)
rows = [json.loads(l) for l in open(inp, encoding="utf-8") if l.strip()]
with open(outp, "a", encoding="utf-8") as f:
    for r in rows:
        t0 = time.time()
        ids = tok(tok.apply_chat_template(r["messages"], tokenize=False, add_generation_prompt=True),
                  add_special_tokens=False, return_tensors="pt")["input_ids"]
        torch.manual_seed(r.get("seed", 42))
        with torch.no_grad():
            out = model.generate(input_ids=ids, max_new_tokens=120, do_sample=True, temperature=0.8)
        text = tok.decode(out[0][ids.shape[1]:], skip_special_tokens=True).strip()
        f.write(json.dumps({"key": r["key"], "text": text, "wall_s": time.time() - t0, "prompt_tokens": int(ids.shape[1]),
                            "eval_count": int(out.shape[1] - ids.shape[1])}, ensure_ascii=False) + "\n")
        f.flush()
