# Kaggle Job A: LoRA fine-tune of gemma-3-1b-it as the CallVerse customer WRITER (role card + history -> real customer message).
# Data: /kaggle/input/callverse-memberb-train/writer_train.jsonl (5,000 anonymised real tweets, split by thread).
# Output: merged fp16 model -> GGUF f16 (quantized to Q4_K_M locally by `ollama create -q q4_K_M`).
import glob, json, os, subprocess, sys, time
t0 = time.time()
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "peft==0.13.2", "gguf", "sentencepiece", "protobuf"], check=False)
import torch
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL = "unsloth/gemma-3-1b-it"   # ungated mirror of google/gemma-3-1b-it (Gemma Terms of Use)
data_path = glob.glob("/kaggle/input/**/writer_train.jsonl", recursive=True)[0]
rows = [json.loads(l) for l in open(data_path, encoding="utf-8")]
tok = AutoTokenizer.from_pretrained(MODEL)
dev = "cuda"
model = AutoModelForCausalLM.from_pretrained(MODEL, torch_dtype=torch.float32, attn_implementation="eager").to(dev)
model.gradient_checkpointing_enable()
model.enable_input_require_grads()
model = get_peft_model(model, LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05, task_type="CAUSAL_LM",
                                         target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]))
MAXLEN = 384


OPENER = {"role": "user", "content": "(The support chat has opened. Write your first message.)"}


def encode(msgs):
    # gemma has no system role: the template folds the system text into the first user turn.
    # Follow-up examples start with the customer's own first message (assistant): add the same opener the kit sends.
    if msgs[1]["role"] == "assistant":
        msgs = [msgs[0], OPENER] + msgs[1:]
    prompt = tok.apply_chat_template(msgs[:-1], tokenize=False, add_generation_prompt=True)
    full = prompt + msgs[-1]["content"] + "<end_of_turn>\n"
    p_ids = tok(prompt, add_special_tokens=False)["input_ids"]
    f_ids = tok(full, add_special_tokens=False)["input_ids"][:MAXLEN]
    labels = [-100] * min(len(p_ids), len(f_ids)) + f_ids[len(p_ids):]
    return f_ids, labels[:len(f_ids)]


enc = [encode(r["messages"]) for r in rows]
enc = [e for e in enc if any(l != -100 for l in e[1])]
print("examples", len(enc), "mean tokens", sum(len(e[0]) for e in enc) / len(enc), flush=True)
opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=2e-4, weight_decay=0.0)
BS, ACC = 8, 2
steps = len(enc) // (BS * ACC)
sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / 20) * max(0.0, 1 - s / max(steps, 1)))
model.train()
pad = tok.pad_token_id or 0
step = 0
for i in range(0, len(enc), BS):
    batch = enc[i:i + BS]
    L = max(len(e[0]) for e in batch)
    ids = torch.tensor([e[0] + [pad] * (L - len(e[0])) for e in batch], device=dev)
    lab = torch.tensor([e[1] + [-100] * (L - len(e[1])) for e in batch], device=dev)
    att = (torch.arange(L, device=dev)[None, :] < torch.tensor([len(e[0]) for e in batch], device=dev)[:, None]).long()
    loss = model(input_ids=ids, attention_mask=att, labels=lab).loss / ACC
    loss.backward()
    if (i // BS + 1) % ACC == 0:
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step(); sched.step(); opt.zero_grad(); step += 1
        if step % 25 == 0:
            print(f"step {step}/{steps} loss {loss.item() * ACC:.3f} elapsed {time.time() - t0:.0f}s", flush=True)
    if time.time() - t0 > 40 * 60:   # hard stop well before the 60 min limit
        print("time cap reached at step", step, flush=True)
        break
model.eval()
try:  # quick sanity sample; never let it block saving
    test = [{"role": "system", "content": "You are a customer of ShopNova (online shop) writing to customer support. Contact reason: a late delivery. Mood: angry. Typos: high. Write only your next message."},
            {"role": "user", "content": "(The support chat has opened. Write your first message.)"}]
    p_ids = tok(tok.apply_chat_template(test, tokenize=False, add_generation_prompt=True), add_special_tokens=False, return_tensors="pt")["input_ids"].to(dev)
    with torch.no_grad():
        out = model.generate(input_ids=p_ids, max_new_tokens=60, do_sample=True, temperature=0.8)
    print("SAMPLE:", tok.decode(out[0][p_ids.shape[1]:], skip_special_tokens=True), flush=True)
except Exception as e:
    print("sample failed:", repr(e)[:300], flush=True)
merged = model.merge_and_unload().to(torch.float16)
os.makedirs("/kaggle/working/merged", exist_ok=True)
merged.save_pretrained("/kaggle/working/merged", safe_serialization=True)
tok.save_pretrained("/kaggle/working/merged")
subprocess.run(["git", "clone", "--depth", "1", "https://github.com/ggml-org/llama.cpp", "/kaggle/tmp_llama"], check=False)
r = subprocess.run([sys.executable, "/kaggle/tmp_llama/convert_hf_to_gguf.py", "/kaggle/working/merged", "--outtype", "f16",
                    "--outfile", "/kaggle/working/callverse-sim-writer-f16.gguf"], capture_output=True, text=True)
print("GGUF convert rc", r.returncode, r.stderr[-1500:], flush=True)
if r.returncode == 0:
    subprocess.run(["rm", "-rf", "/kaggle/working/merged"])
json.dump({"steps": step, "planned_steps": steps, "examples": len(enc), "seconds": time.time() - t0, "model": MODEL,
           "lora": {"r": 16, "alpha": 32, "dropout": 0.05}, "lr": 2e-4, "batch": BS * ACC, "epochs": 1, "maxlen": MAXLEN},
          open("/kaggle/working/train_info.json", "w"))
print("done", time.time() - t0)
