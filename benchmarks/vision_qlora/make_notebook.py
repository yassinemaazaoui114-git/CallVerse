"""Write CallVerse_Qwen3VL_QLoRA_Training.ipynb from the source files in this folder.

The notebook is self-contained: it carries cv_vision_lib.py, build_dataset.py and manifest.jsonl inside
%%writefile cells, so Kaggle needs nothing from this repository. Re-run this script after any change:
    python make_notebook.py
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "CallVerse_Qwen3VL_QLoRA_Training.ipynb")


def src(name):
    return open(os.path.join(HERE, name), encoding="utf-8").read()


cells = []


def md(text):
    cells.append({"cell_type": "markdown", "metadata": {}, "source": text.strip("\n").splitlines(True)})


def code(text):
    cells.append({"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [],
                  "source": text.strip("\n").splitlines(True)})


md("""
# CallVerse — Qwen3-VL-2B QLoRA for visual evidence (ShopNova + Atlas Travel)

**What this notebook does:** it builds the 150-photo CallVerse vision dataset from its public sources,
measures the original Qwen3-VL-2B-Instruct, fine-tunes it with QLoRA (4-bit NF4 + LoRA), selects the best
checkpoint on the **validation** split only, compares the 3 systems on the held-out **test** split, and packs
everything into `callverse_vision_qlora_results.zip`.

**How to run on Kaggle:** Settings → Accelerator **GPU T4 x2** (or P100) → Settings → **Internet on** → **Run All**.
When it finishes, download `/kaggle/working/callverse_vision_qlora_results.zip` from the Output panel.

**What the model learns:** only what is *visible* in a photo (visual evidence). It never sees the customer's text
and never outputs intent, emotion, refund eligibility or any business decision — Intake (text) and the
Coordinator (rules) do that. The photos are all real; the customer messages in the dataset are written examples
used later for the late-fusion tests in CallVerse, not for this training.
""")

md("## Cell 1 — Environment and GPU detection")
code(r'''
import json, os, platform, subprocess, sys, time
T_START = time.time()
WORK = "/kaggle/working" if os.path.isdir("/kaggle/working") else os.path.abspath("work")
os.makedirs(WORK, exist_ok=True)
os.chdir(WORK)
import torch
if not torch.cuda.is_available():
    raise SystemExit("No GPU found. In Kaggle: Settings -> Accelerator -> GPU T4 x2 (or P100), then Run All again.")
dev = torch.cuda.get_device_properties(0)
CAP = torch.cuda.get_device_capability(0)
BF16 = torch.cuda.is_bf16_supported() and CAP[0] >= 8
env = {
    "python": sys.version.split()[0], "platform": platform.platform(),
    "torch": torch.__version__, "cuda_runtime": torch.version.cuda, "cudnn": torch.backends.cudnn.version(),
    "gpu_count": torch.cuda.device_count(), "gpu": dev.name, "gpu_vram_gb": round(dev.total_memory / 2**30, 1),
    "compute_capability": f"{CAP[0]}.{CAP[1]}", "bf16_supported": BF16, "fp16_supported": True,
}
try:
    env["nvidia_smi"] = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
                                        "--format=csv,noheader"], capture_output=True, text=True).stdout.strip()
except Exception as e:
    env["nvidia_smi"] = f"unavailable: {e}"
print(json.dumps(env, indent=1))
''')

md("""
## Cell 2 — Dependencies
Kaggle's own PyTorch / torchvision (built for its CUDA) are kept. Qwen3-VL needs transformers ≥ 4.57; the pinned
versions below are the ones the code was checked with (CPU check, see README). If Kaggle's torch is older than 2.6,
transformers 5 cannot run and the cell falls back to transformers 4.57.x.
""")
code(r'''
from packaging.version import Version
TORCH_OK_FOR_TF5 = Version(torch.__version__.split("+")[0]) >= Version("2.6")
tf_spec = "transformers==5.22.1" if TORCH_OK_FOR_TF5 else "transformers>=4.57.1,<4.58"
pkgs = [tf_spec, "peft==0.21.2", "accelerate==1.15.0", "bitsandbytes==0.50.2", "pyarrow", "scikit-learn", "matplotlib"]
print("installing:", pkgs)
r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", *pkgs], capture_output=True, text=True)
print(r.stdout[-2000:], r.stderr[-3000:])
import transformers, peft, accelerate   # first import happens here, after the install
from transformers import AutoProcessor, Qwen3VLForConditionalGeneration, BitsAndBytesConfig
try:
    import bitsandbytes as bnb
    BNB_VERSION = bnb.__version__
except Exception as e:
    BNB_VERSION = f"import failed: {e}"
env.update({"transformers": transformers.__version__, "peft": peft.__version__, "accelerate": accelerate.__version__,
            "bitsandbytes": BNB_VERSION})
print({k: env[k] for k in ("torch", "transformers", "peft", "accelerate", "bitsandbytes")})
''')

md("### Shared code (written from the repository files `cv_vision_lib.py` and `build_dataset.py`)")
code("%%writefile cv_vision_lib.py\n" + src("cv_vision_lib.py"))
code("%%writefile build_dataset.py\n" + src("build_dataset.py"))
code("%%writefile manifest.jsonl\n" + src("manifest.jsonl"))

md("""
## Cell 3 — Dataset preparation
Uses an attached Kaggle dataset if one contains `dataset.jsonl`; otherwise downloads the 150 photos from their
pinned public sources (Hugging Face + GitHub, ~1.3 GB, about 2-4 minutes) and checks each photo's sha256.
""")
code(r'''
import glob, collections, random
import numpy as np
sys.path.insert(0, WORK)
import cv_vision_lib as L
import build_dataset as B
SEED = 42
random.seed(SEED); np.random.seed(SEED); torch.manual_seed(SEED); torch.cuda.manual_seed_all(SEED)
torch.backends.cudnn.benchmark = False

attached = sorted(glob.glob("/kaggle/input/**/dataset.jsonl", recursive=True))
if attached:
    DATA = os.path.dirname(attached[0])
    print("using attached dataset:", DATA)
    summary = json.load(open(os.path.join(DATA, "dataset_summary.json")))
else:
    DATA = os.path.join(WORK, "callverse_vision_dataset")
    try:
        summary = B.build("manifest.jsonl", DATA, os.path.join(WORK, "source_cache"))
    except OSError as e:
        raise SystemExit(f"Download failed ({e}). In Kaggle turn Settings -> Internet ON, then Run All again.")
rows = L.load_rows(DATA)
# checks: required fields, files, decodable images, label values
need = {"id", "image", "domain", "group", "split", "target"}
for r in rows:
    miss = need - set(r)
    if miss:
        raise ValueError(f"{r.get('id')}: missing fields {miss}")
    if not os.path.isfile(r["image_path"]):
        raise FileNotFoundError(r["image_path"])
    L.open_image(r["image_path"])
    ok, why = L.parse_output(L.answer_text(r["target"]))
    if ok is None:
        raise ValueError(f"{r['id']}: target is not a valid answer ({why})")
split = {s: [r for r in rows if r["split"] == s] for s in ("train", "val", "test")}
# leakage: a group (same suitcase / box / hotel / room) must sit in one split only
g2s = collections.defaultdict(set)
for r in rows:
    g2s[r["group"]].add(r["split"])
leaks = [g for g, s in g2s.items() if len(s) > 1]
assert not leaks, f"leakage: {leaks}"
# near-duplicate check ACROSS splits (difference hash on the stored photos)
from PIL import Image
dh = {r["id"]: B.dhash(Image.open(r["image_path"])) for r in rows}
cross = min((B.hamming(dh[a["id"]], dh[b["id"]]), a["id"], b["id"])
            for a in rows for b in rows if a["split"] < b["split"])
print("closest photo pair across splits (dHash distance, 0 = identical):", cross)
print(json.dumps({s: len(v) for s, v in split.items()}), "photos")
tab = collections.Counter((r["target"]["issue_type"], r["split"]) for r in rows)
print(f"{'issue_type':24s} train  val test")
for c in L.ISSUE_TYPES:
    print(f"{c:24s} {tab[(c,'train')]:5d} {tab[(c,'val')]:4d} {tab[(c,'test')]:4d}")
json.dump(summary, open(os.path.join(WORK, "dataset_summary.json"), "w"), indent=1)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
show = [r for r in (next((r for r in split["train"] if r["target"]["issue_type"] == c), None) for c in L.ISSUE_TYPES) if r]
fig, ax = plt.subplots(2, 4, figsize=(16, 8))
for a, r in zip(ax.ravel(), show):
    a.imshow(L.open_image(r["image_path"])); a.set_title(f"{r['id']} {r['target']['issue_type']}", fontsize=9); a.axis("off")
plt.tight_layout(); plt.savefig("sample_images.png", dpi=80); plt.show()
''')

md("""
## Cell 4 — Baseline: original Qwen3-VL-2B (before fine-tuning)
Loaded exactly as it will be for training (4-bit NF4, same image size, greedy decoding), so the comparison is fair.
Two prompts: the original short prompt (style of Molka's benchmark) and the improved prompt (allowed values +
grounding rules). Predictions on **val** and **test** are saved; test numbers are only *reported* in Cell 8 and
never used to choose anything.
""")
code(r'''
BASE_MODEL = "Qwen/Qwen3-VL-2B-Instruct"
BASE_REVISION = "89644892e4d85e24eaac8bacfd4f463576704203"   # pinned Hugging Face commit
MAX_PIXELS = 512 * 512      # at most 256 image tokens per photo (16-px patches, 2x2 merge)
MIN_PIXELS = 128 * 128
COMPUTE = torch.bfloat16 if BF16 else torch.float16
QUANT = "nf4"               # set to "none" automatically if bitsandbytes 4-bit is not usable on this GPU

processor = AutoProcessor.from_pretrained(BASE_MODEL, revision=BASE_REVISION)
processor.image_processor.size = {"longest_edge": MAX_PIXELS, "shortest_edge": MIN_PIXELS}

def load_base(compute=None):
    """Base model in 4-bit NF4 (vision encoder + lm_head kept un-quantised for image fidelity)."""
    global QUANT
    compute = compute or COMPUTE
    if QUANT == "nf4":
        try:
            q = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                                   bnb_4bit_compute_dtype=compute, llm_int8_skip_modules=["visual", "lm_head"])
            m = Qwen3VLForConditionalGeneration.from_pretrained(BASE_MODEL, revision=BASE_REVISION,
                                                                quantization_config=q, dtype=compute, device_map={"": 0})
            return m
        except Exception as e:
            print("4-bit loading failed, falling back to 16-bit LoRA:", repr(e)[:300])
            QUANT = "none"
    return Qwen3VLForConditionalGeneration.from_pretrained(BASE_MODEL, revision=BASE_REVISION, dtype=compute,
                                                           device_map={"": 0})

L.AMP_DTYPE = COMPUTE
base = load_base()
base.eval()
print("quantisation:", QUANT, "| compute dtype:", COMPUTE, "| GPU memory after load:",
      round(torch.cuda.memory_allocated() / 2**30, 2), "GB")
# fp16 safety check on 3 photos: if the model gives NaN/inf losses in fp16, switch to fp32 compute.
probe = [float(L.eval_loss(base, processor, [r], L.PROMPT_IMPROVED)) for r in split["train"][:3]]
if not all(np.isfinite(probe)):
    print("non-finite loss in", COMPUTE, "-> reloading with float32 compute")
    COMPUTE = torch.float32; L.AMP_DTYPE = None
    del base; torch.cuda.empty_cache(); base = load_base(torch.float32); base.eval()
print("probe losses:", [round(x, 3) for x in probe])
env.update({"quantisation": QUANT, "compute_dtype": str(COMPUTE)})

PRED = {}   # (system, split) -> predictions
for system, prompt in (("base_original_prompt", L.PROMPT_BASE), ("base_improved_prompt", L.PROMPT_IMPROVED)):
    for s in ("val", "test"):
        print(f"{system} on {s}:")
        PRED[(system, s)] = L.predict(base, processor, split[s], prompt)
BASE_VAL = {sy: L.metrics(split["val"], PRED[(sy, "val")]) for sy in ("base_original_prompt", "base_improved_prompt")}
for sy, m in BASE_VAL.items():
    print(f"VAL {sy}: accuracy {m['accuracy']:.3f}  macro-F1 {m['macro_f1']:.3f}  damage recall "
          f"{m['damage_recall']:.3f}  JSON valid {m['json_validity']:.3f}  latency {m['latency_s']['mean']:.2f} s")
''')

md("""
## Cell 5 — QLoRA configuration
LoRA only on the language model's linear layers (q/k/v/o + MLP). The vision encoder stays frozen: with ~100
training photos, training it would mostly over-fit. The image still drives the update: the LoRA layers read the
image tokens, and the check below compares the loss with the right photo vs. a swapped photo.
""")
code(r'''
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
VRAM = env["gpu_vram_gb"]
EFFECTIVE_BATCH = 8
CFG_BASE = {"r": 16, "alpha": 32, "dropout": 0.05, "lr": 1e-4, "epochs": 3, "grad_accum": EFFECTIVE_BATCH,
            "batch_size": 1, "seed": SEED, "patience": 2, "prompt": L.PROMPT_IMPROVED,
            "max_pixels": MAX_PIXELS, "quantisation": QUANT, "compute_dtype": str(COMPUTE),
            "gradient_checkpointing": True, "target_modules": L.lora_target_regex()}
print("batch 1 x gradient accumulation", EFFECTIVE_BATCH, "(VRAM", VRAM, "GB)")

def make_peft(cfg):
    torch.manual_seed(cfg["seed"])
    m = load_base(COMPUTE)
    m.config.use_cache = False
    if QUANT == "nf4":
        m = prepare_model_for_kbit_training(m, use_gradient_checkpointing=True,
                                            gradient_checkpointing_kwargs={"use_reentrant": False})
    else:
        m.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
        m.enable_input_require_grads()
    lc = LoraConfig(r=cfg["r"], lora_alpha=cfg["alpha"], lora_dropout=cfg["dropout"],
                    target_modules=cfg["target_modules"], bias="none", task_type="CAUSAL_LM")
    pm = get_peft_model(m, lc)
    for p in pm.parameters():          # LoRA weights in float32 (needed by the fp16 GradScaler, more stable)
        if p.requires_grad:
            p.data = p.data.float()
    return pm

del base; torch.cuda.empty_cache()
model = make_peft(CFG_BASE)
model.print_trainable_parameters()
names = [n for n, p in model.named_parameters() if p.requires_grad]
assert names and not any("visual" in n for n in names), "LoRA must sit on the language model only"
# genuine image-conditioned update: image tokens present, gradients flow, the image changes the loss
r0 = split["train"][0]
b0 = L.encode_for_training(processor, L.open_image(r0["image_path"]), L.PROMPT_IMPROVED, L.answer_text(r0["target"])).to(0)
n_img = L.count_image_tokens(processor, b0["input_ids"]); n_ans = int((b0["labels"] != -100).sum())
assert n_img > 0 and 0 < n_ans < b0["input_ids"].shape[1]
model.train()
with L._autocast():
    loss0 = model(**b0).loss
loss0.backward()
gsum = sum(float(p.grad.abs().sum()) for n, p in model.named_parameters() if p.requires_grad and p.grad is not None)
model.zero_grad(set_to_none=True)
assert np.isfinite(gsum) and gsum > 0, "no gradient reached the LoRA weights"
probe_rows = split["val"][:8]
CHECK = {"image_tokens_example": n_img, "answer_tokens_example": n_ans, "first_loss": loss0.item(), "grad_abs_sum": gsum,
         "val8_loss_true_images_before": L.eval_loss(model, processor, probe_rows, L.PROMPT_IMPROVED),
         "val8_loss_swapped_images_before": L.eval_loss(model, processor, probe_rows, L.PROMPT_IMPROVED, shuffle_images=True)}
print(json.dumps(CHECK, indent=1))
''')

md("""
## Cell 6 — QLoRA training (main configuration)
Batch 1 × 8 accumulation, cosine schedule, answer-only loss, validation loss + validation generation metrics after
every epoch, adapter saved every epoch (`ckpt/<run>/epoch_k`, resume-safe), early stop after 2 epochs without a
better validation loss. The best epoch is chosen on **validation macro-F1** (tie: lower validation loss).
""")
code(r'''
RUNS = {}
def run_config(name, cfg):
    global model
    out_dir = os.path.join(WORK, "ckpt", name)
    def on_epoch(ep, ep_dir):
        preds = L.predict(model, processor, split["val"], cfg["prompt"])
        m = L.metrics(split["val"], preds, n_boot=200)
        torch.cuda.empty_cache()
        print(f"    val accuracy {m['accuracy']:.3f}  macro-F1 {m['macro_f1']:.3f}  damage recall {m['damage_recall']:.3f}"
              f"  JSON valid {m['json_validity']:.3f}")
        return {"val_accuracy": m["accuracy"], "val_macro_f1": m["macro_f1"], "val_damage_recall": m["damage_recall"],
                "val_json_validity": m["json_validity"], "adapter_dir": ep_dir}
    t0 = time.time()
    hist = L.train_run(model, processor, split["train"], split["val"], cfg, out_dir,
                       use_scaler=(COMPUTE == torch.float16), epoch_callback=on_epoch)
    best = max(hist, key=lambda h: (h["val_macro_f1"], -h["val_loss"]))
    RUNS[name] = {"config": {k: v for k, v in cfg.items() if k != "prompt"}, "history": hist,
                  "best_epoch": best["epoch"], "best": best, "minutes": round((time.time() - t0) / 60, 1)}
    print(f"{name}: best epoch {best['epoch']} (val macro-F1 {best['val_macro_f1']:.3f}, val loss {best['val_loss']:.4f})")
    json.dump(RUNS, open(os.path.join(WORK, "training_metrics.json"), "w"), indent=1, default=str)

run_config("r16_lr1e-4", CFG_BASE)
''')

md("""
## Cell 7 — Small, targeted search (validation only)
Two variants, each changing ONE thing from the main run: a smaller adapter (r = 8) and a lower learning rate
(5e-5). They run only if the time budget allows. Selection uses validation numbers only; the test split is never
looked at here.
""")
code(r'''
TIME_BUDGET_H = 8.0   # Kaggle GPU sessions stop at 12 h; keep a wide margin
VARIANTS = {"r8_lr1e-4": {**CFG_BASE, "r": 8, "alpha": 16}, "r16_lr5e-5": {**CFG_BASE, "lr": 5e-5}}
per_run_h = RUNS["r16_lr1e-4"]["minutes"] / 60
for name, cfg in VARIANTS.items():
    used_h = (time.time() - T_START) / 3600
    if used_h + per_run_h * 1.2 > TIME_BUDGET_H:
        print(f"skip {name}: {used_h:.1f} h used, about {per_run_h:.1f} h needed")
        continue
    del model; torch.cuda.empty_cache()
    model = make_peft(cfg)
    run_config(name, cfg)
BEST_RUN = max(RUNS, key=lambda n: (RUNS[n]["best"]["val_macro_f1"], -RUNS[n]["best"]["val_loss"]))
SEL = RUNS[BEST_RUN]
print("selected on validation:", BEST_RUN, "epoch", SEL["best_epoch"], "| val macro-F1", round(SEL["best"]["val_macro_f1"], 3))
for n, r in RUNS.items():
    print(f"  {n:12s} " + "  ".join(f"ep{h['epoch']}: loss {h['val_loss']:.3f} F1 {h['val_macro_f1']:.3f}" for h in r["history"]))
''')

md("""
## Cell 8 — Final benchmark on the held-out test split
Same 25 test photos, same decoding, same scoring for: (1) original model + original prompt, (2) original model +
improved prompt, (3) fine-tuned adapter + improved prompt. 95 % bootstrap intervals are shown because the test
split is small; the paired bootstrap tells how sure we are that (3) beats (2).
""")
code(r'''
import csv
from peft import PeftModel
del model; torch.cuda.empty_cache()
# load exactly as CallVerse will: base model + saved adapter folder (checks that the checkpoint loads)
model = PeftModel.from_pretrained(load_base(COMPUTE), SEL["best"]["adapter_dir"])
model.eval()
model.config.use_cache = True
print("fine-tuned test predictions:")
PRED[("finetuned_qlora", "test")] = L.predict(model, processor, split["test"], L.PROMPT_IMPROVED)
PRED[("finetuned_qlora", "val")] = L.predict(model, processor, split["val"], L.PROMPT_IMPROVED)
CHECK["val8_loss_true_images_after"] = L.eval_loss(model, processor, probe_rows, L.PROMPT_IMPROVED)
CHECK["val8_loss_swapped_images_after"] = L.eval_loss(model, processor, probe_rows, L.PROMPT_IMPROVED, shuffle_images=True)
print("image check (lower loss with the true photo = the adapter uses the image):", json.dumps(CHECK, indent=1))

SYSTEMS = ["base_original_prompt", "base_improved_prompt", "finetuned_qlora"]
RES = {(sy, s): L.metrics(split[s], PRED[(sy, s)]) for sy in SYSTEMS for s in ("val", "test")}
with open("benchmark_comparison.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["system", "split", "n", "accuracy", "accuracy_ci95", "macro_precision", "macro_recall", "macro_f1",
                "macro_f1_ci95", "damage_recall", "damage_recall_ci95", "damage_precision", "false_alarm_rate",
                "damage_recall_lenient", "json_validity", "latency_mean_s", "latency_median_s", "latency_p95_s"])
    for (sy, s), m in RES.items():
        w.writerow([sy, s, m["n"], round(m["accuracy"], 4), m["ci95"]["accuracy"], round(m["macro_precision"], 4),
                    round(m["macro_recall"], 4), round(m["macro_f1"], 4), m["ci95"]["macro_f1"], round(m["damage_recall"], 4),
                    m["ci95"]["damage_recall"], round(m["damage_precision"], 4), round(m["false_alarm_rate"], 4),
                    round(m["damage_recall_lenient"], 4), round(m["json_validity"], 4), round(m["latency_s"]["mean"], 3), round(m["latency_s"]["median"], 3),
                    round(m["latency_s"]["p95"], 3)])
print(open("benchmark_comparison.csv").read())
print("per-class F1 on test:")
for c in sorted({r["target"]["issue_type"] for r in split["test"]}):
    print(f"  {c:24s} " + "  ".join(f"{sy}: {RES[(sy,'test')]['per_class'][c]['f1']:.2f}" for sy in SYSTEMS))
PAIRED = {"finetuned_vs_improved_prompt": L.paired_bootstrap(split["test"], PRED[("base_improved_prompt", "test")], PRED[("finetuned_qlora", "test")]),
          "finetuned_vs_original": L.paired_bootstrap(split["test"], PRED[("base_original_prompt", "test")], PRED[("finetuned_qlora", "test")])}
print("paired bootstrap on test accuracy:", json.dumps(PAIRED, indent=1))

# confusion matrices (rows = truth, columns = prediction, last column = invalid output)
cols = L.ISSUE_TYPES + ["INVALID"]
fig, axes = plt.subplots(1, 3, figsize=(24, 7))
for ax, sy in zip(axes, SYSTEMS):
    M = np.zeros((len(L.ISSUE_TYPES), len(cols)), dtype=int)
    for r, p in zip(split["test"], PRED[(sy, "test")]):
        M[L.ISSUE_TYPES.index(r["target"]["issue_type"]), cols.index(p["parsed"]["issue_type"] if p["parsed"] else "INVALID")] += 1
    ax.imshow(M, cmap="Blues")
    ax.set_xticks(range(len(cols))); ax.set_xticklabels(cols, rotation=60, ha="right", fontsize=8)
    ax.set_yticks(range(len(L.ISSUE_TYPES))); ax.set_yticklabels(L.ISSUE_TYPES, fontsize=8)
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            if M[i, j]:
                ax.text(j, i, M[i, j], ha="center", va="center", fontsize=9)
    ax.set_title(f"{sy} (test, n={len(split['test'])})")
plt.tight_layout(); plt.savefig("confusion_matrix.png", dpi=90); plt.show()

with open("error_analysis.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["system", "split", "id", "domain", "gold_issue", "pred_issue", "gold_damage", "pred_damage", "parse",
                "correct", "gold_description", "raw_output"])
    for sy in SYSTEMS:
        for s in ("val", "test"):
            for r, p in zip(split[s], PRED[(sy, s)]):
                pi = p["parsed"]["issue_type"] if p["parsed"] else None
                w.writerow([sy, s, r["id"], r["domain"], r["target"]["issue_type"], pi, r["target"]["visible_damage"],
                            p["parsed"]["visible_damage"] if p["parsed"] else None, p["parse"], pi == r["target"]["issue_type"],
                            r["target"]["description"], p["raw"]])
with open("predictions.jsonl", "w") as f:
    for (sy, s), ps in PRED.items():
        for p in ps:
            f.write(json.dumps({"system": sy, "split": s, **p}, ensure_ascii=False) + "\n")
''')

md("## Cell 9 — Save the best adapter")
code(r'''
import shutil
BEST_DIR = os.path.join(WORK, "best_adapter")
shutil.rmtree(BEST_DIR, ignore_errors=True)
shutil.copytree(SEL["best"]["adapter_dir"], BEST_DIR)
processor.save_pretrained(BEST_DIR)          # same image size settings as in training
info = {"base_model": BASE_MODEL, "base_revision": BASE_REVISION, "run": BEST_RUN, "epoch": SEL["best_epoch"],
        "quantisation_used_in_training": QUANT, "compute_dtype": str(COMPUTE), "max_pixels": MAX_PIXELS,
        "min_pixels": MIN_PIXELS, "prompt": L.PROMPT_IMPROVED, "output_keys": L.KEYS, "issue_types": L.ISSUE_TYPES,
        "selected_on": "validation macro-F1 (tie: validation loss)", "load_note":
        "Load Qwen3VLForConditionalGeneration(BASE_MODEL, revision=BASE_REVISION) in 4-bit NF4 (or 16-bit), then "
        "PeftModel.from_pretrained(model, best_adapter). Use the prompt above and greedy decoding."}
json.dump(info, open(os.path.join(BEST_DIR, "callverse_adapter_info.json"), "w"), indent=1)
print(os.listdir(BEST_DIR), round(sum(os.path.getsize(os.path.join(BEST_DIR, f)) for f in os.listdir(BEST_DIR)) / 2**20, 1), "MB")
''')

md("## Cell 10 — Package all results")
code(r'''
import zipfile
json.dump({**CFG_BASE, "prompt": L.PROMPT_IMPROVED, "runs": {n: r["config"] for n, r in RUNS.items()},
           "selected_run": BEST_RUN, "selected_epoch": SEL["best_epoch"], "seed": SEED,
           "base_model": BASE_MODEL, "base_revision": BASE_REVISION}, open("training_config.json", "w"), indent=1, default=str)
TM = {"runs": RUNS, "selected_run": BEST_RUN, "image_conditioning_check": CHECK, "paired_bootstrap_test": PAIRED,
      "metrics": {f"{sy}|{s}": m for (sy, s), m in RES.items()}, "baseline_val": BASE_VAL}
json.dump(TM, open("training_metrics.json", "w"), indent=1, default=str)
env["total_runtime_min"] = round((time.time() - T_START) / 60, 1)
json.dump(env, open("environment_info.json", "w"), indent=1)
shutil.copy(os.path.join(DATA, "dataset.jsonl"), "dataset.jsonl")
if os.path.exists(os.path.join(DATA, "review_queue.csv")):
    shutil.copy(os.path.join(DATA, "review_queue.csv"), "review_queue.csv")
FILES = ["training_metrics.json", "benchmark_comparison.csv", "confusion_matrix.png", "error_analysis.csv",
         "dataset_summary.json", "training_config.json", "environment_info.json", "predictions.jsonl",
         "dataset.jsonl", "review_queue.csv", "sample_images.png"]
ZIP = os.path.join(WORK, "callverse_vision_qlora_results.zip")
with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as z:
    for f in FILES:
        if os.path.exists(f):
            z.write(f)
    for f in os.listdir(BEST_DIR):
        z.write(os.path.join(BEST_DIR, f), os.path.join("best_adapter", f))
mb = os.path.getsize(ZIP) / 2**20
print(f"{ZIP}: {mb:.1f} MB")
if mb > 500:
    print("ZIP is large: download best_adapter/ separately from the Output panel (Kaggle keeps /kaggle/working).")
# keep the output small: the per-epoch checkpoints and the photo cache are not needed after packaging
shutil.rmtree(os.path.join(WORK, "source_cache"), ignore_errors=True)
print("total runtime:", env["total_runtime_min"], "min")
''')

nb = {"cells": cells, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                                   "language_info": {"name": "python"},
                                   "kaggle": {"accelerator": "gpu", "isInternetEnabled": True}},
      "nbformat": 4, "nbformat_minor": 5}
for i, c in enumerate(nb["cells"]):
    c["id"] = f"cell-{i:02d}"
json.dump(nb, open(OUT, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("wrote", OUT, len(cells), "cells")
