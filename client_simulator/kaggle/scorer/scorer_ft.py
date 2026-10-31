# Kaggle Job B: fine-tune a small encoder (all-MiniLM-L12-v2) as a 1-5 satisfaction SCORER (regression on the ordinal score).
# Data: /kaggle/input/callverse-memberb-train/scorer_traindev.jsonl (REAL train + dev rows of Flipkart CSAT, Olist, TripAdvisor, USS).
# Output: ONNX fp32 + int8 for CPU, tokenizer.json, dev predictions.
import glob, json, os, subprocess, sys, time
t0 = time.time()
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "onnx", "onnxruntime", "onnxscript"], check=False)
import numpy as np
import pandas as pd
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

MODEL = "sentence-transformers/all-MiniLM-L12-v2"   # Apache 2.0
df = pd.read_json(glob.glob("/kaggle/input/**/scorer_traindev.jsonl", recursive=True)[0], lines=True)
tr, dv = df[df.split == "train"], df[df.split == "dev"]
# balance sources: cap the large ones, repeat the small USS set
parts = [tr[tr.source == "csat"].sample(min(40000, (tr.source == "csat").sum()), random_state=42),
         tr[tr.source == "olist"].sample(min(40000, (tr.source == "olist").sum()), random_state=42),
         tr[tr.source == "tripadvisor"], pd.concat([tr[tr.source == "uss"]] * 5)]
tr = pd.concat(parts).sample(frac=1, random_state=42)
dvs = dv.groupby("source", group_keys=False).apply(lambda g: g.sample(min(2000, len(g)), random_state=42))
print("train rows", len(tr), tr.source.value_counts().to_dict(), flush=True)
tok = AutoTokenizer.from_pretrained(MODEL)
model = AutoModelForSequenceClassification.from_pretrained(MODEL, num_labels=1).cuda()
MAXLEN, BS, EPOCHS = 256, 64, 2


def batches(d, shuffle):
    idx = np.random.permutation(len(d)) if shuffle else np.arange(len(d))
    for i in range(0, len(d), BS):
        b = d.iloc[idx[i:i + BS]]
        x = tok(list(b.text), truncation=True, max_length=MAXLEN, padding=True, return_tensors="pt")
        yield {k: v.cuda() for k, v in x.items()}, torch.tensor(((b.label.values - 3) / 2).astype("float32")).cuda()


opt = torch.optim.AdamW(model.parameters(), lr=5e-5, weight_decay=0.01)
total = EPOCHS * (len(tr) // BS + 1)
sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / 200) * max(0.0, 1 - s / total))
scaler = torch.cuda.amp.GradScaler()
step = 0
for ep in range(EPOCHS):
    model.train()
    for x, y in batches(tr, True):
        with torch.autocast("cuda", dtype=torch.float16):
            loss = torch.nn.functional.mse_loss(model(**x).logits.squeeze(-1).float(), y)
        scaler.scale(loss).backward(); scaler.step(opt); scaler.update(); opt.zero_grad(); sched.step(); step += 1
        if step % 200 == 0:
            print(f"ep {ep} step {step}/{total} loss {loss.item():.4f} {time.time() - t0:.0f}s", flush=True)
        if time.time() - t0 > 45 * 60:
            break
    if time.time() - t0 > 45 * 60:
        print("time cap", flush=True); break
model.eval()
preds = []
with torch.no_grad():
    for x, _ in batches(dvs, False):
        preds += (model(**x).logits.squeeze(-1).float().cpu().numpy() * 2 + 3).tolist()
dvs = dvs.assign(pred=preds)
dvs[["id", "source", "label", "pred"]].to_csv("/kaggle/working/dev_preds.csv", index=False)
for s, g in dvs.groupby("source"):
    print(s, "dev MAE", float(np.mean(np.abs(np.clip(np.round(g.pred), 1, 5) - g.label))), flush=True)
model = model.float().cpu()
os.makedirs("/kaggle/working/onnx", exist_ok=True)
model.save_pretrained("/kaggle/working/hf_model")   # keep the weights even if the ONNX export fails
x = tok(["hello"], return_tensors="pt")
torch.onnx.export(model, (x["input_ids"], x["attention_mask"]), "/kaggle/working/onnx/scorer.onnx",
                  input_names=["input_ids", "attention_mask"], output_names=["score"], opset_version=17,
                  dynamic_axes={"input_ids": {0: "b", 1: "t"}, "attention_mask": {0: "b", 1: "t"}, "score": {0: "b"}}, dynamo=False)
from onnxruntime.quantization import QuantType, quantize_dynamic
quantize_dynamic("/kaggle/working/onnx/scorer.onnx", "/kaggle/working/onnx/scorer_int8.onnx", weight_type=QuantType.QInt8)
tok.save_pretrained("/kaggle/working/onnx")
json.dump({"model": MODEL, "steps": step, "planned": total, "epochs": EPOCHS, "lr": 5e-5, "batch": BS, "maxlen": MAXLEN,
           "train_rows": len(tr), "train_by_source": tr.source.value_counts().to_dict(), "target": "(score-3)/2, MSE",
           "seconds": time.time() - t0}, open("/kaggle/working/train_info.json", "w"))
print("done", time.time() - t0)
