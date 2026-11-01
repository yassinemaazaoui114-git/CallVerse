"""CallVerse vision: prompts, data encoding, evaluation and QLoRA training for Qwen3-VL-2B.

One file, used by the Kaggle notebook (copied in with %%writefile) and by the local CPU checks.

Design rules (CLAUDE.md + task):
- The vision model sees ONLY the photo. It never sees the customer's words: it reports what is VISIBLE
  (visual evidence). The customer's intent comes from Intake (text). They are joined later (late fusion).
- The answer is one JSON object with fixed keys. No intent, no refund decision, no emotion, no business facts.
- Loss is computed only on the answer tokens (the prompt and the image tokens are masked with -100).
"""
import json
import math
import os
import random
import re
import time

ISSUE_TYPES = ["cracked_screen", "screen_display_defect", "damaged_packaging", "damaged_luggage",
               "dirty_or_messy_room", "damaged_room_fixture", "no_visible_issue", "unclear"]
DAMAGE_TYPES = ISSUE_TYPES[:6]
KEYS = ["visible_damage", "object", "issue_type", "description", "confidence_level", "requires_review"]

# Mixed precision used for EVERY forward pass (train, eval loss, generation): None = off (CPU / fp32).
# The notebook sets it to torch.bfloat16 or torch.float16 after checking the GPU.
AMP_DTYPE = None


def _autocast():
    import contextlib
    import torch
    if AMP_DTYPE is None or not torch.cuda.is_available():
        return contextlib.nullcontext()
    return torch.autocast("cuda", dtype=AMP_DTYPE)

# Prompt 1 = the original style used in Molka's benchmark (short, one question) + our output keys.
PROMPT_BASE = (
    "Look carefully at this image sent by a customer. Is there clearly visible physical damage? "
    "Return only JSON with the keys visible_damage (true, false or null), object, issue_type, description, "
    "confidence_level and requires_review."
)

# Prompt 2 = improved prompt: allowed values, grounding rules, uncertainty. Used for the base model AND for
# fine-tuning, so the "prompt only" and "fine-tuned" rows of the benchmark differ only by the training.
PROMPT_IMPROVED = (
    "You check photos sent to a customer-service centre (an online shop and a travel agency).\n"
    "Describe ONLY what is visible in the photo. Do not guess the customer's wishes, feelings, identity, "
    "orders, bookings, payments or any decision.\n"
    "Return one JSON object and nothing else, with exactly these keys:\n"
    '{"visible_damage": true | false | null, "object": "<main object, snake_case>", '
    '"issue_type": "<one value from the list>", "description": "<one short sentence about what is visible>", '
    '"confidence_level": "high" | "medium" | "low", "requires_review": true | false}\n'
    "issue_type values: cracked_screen, screen_display_defect, damaged_packaging, damaged_luggage, "
    "dirty_or_messy_room, damaged_room_fixture, no_visible_issue, unclear.\n"
    "Rules: visible_damage is true only for clearly visible damage or dirt; false when the object looks intact "
    "or clean (issue_type no_visible_issue); null when the photo does not allow a decision (issue_type unclear, "
    "confidence_level low). requires_review is true whenever visible_damage is not false or confidence is not high."
)


def answer_text(target):
    """Canonical answer string (fixed key order) the model learns to write."""
    return json.dumps({k: target[k] for k in KEYS}, ensure_ascii=False)


def load_rows(dataset_dir):
    rows = [json.loads(l) for l in open(os.path.join(dataset_dir, "dataset.jsonl"), encoding="utf-8") if l.strip()]
    for r in rows:
        r["image_path"] = os.path.join(dataset_dir, r["image"])
    return rows


def open_image(path):
    from PIL import Image
    with Image.open(path) as im:
        return im.convert("RGB")


# ---------------- parsing ----------------
def parse_output(text):
    """Return (dict or None, reason). Valid = one JSON object with the 6 keys and allowed values."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None, "no_json"
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None, "bad_json"
    if not isinstance(obj, dict) or set(obj) != set(KEYS):
        return None, "wrong_keys"
    if obj["visible_damage"] not in (True, False, None):
        return None, "bad_visible_damage"
    if obj["issue_type"] not in ISSUE_TYPES:
        return None, "bad_issue_type"
    if obj["confidence_level"] not in ("high", "medium", "low"):
        return None, "bad_confidence"
    if not isinstance(obj["requires_review"], bool) or not isinstance(obj["description"], str):
        return None, "bad_types"
    return obj, "ok"


def lenient_damage(raw):
    """visible_damage read from ANY JSON-looking answer (even with wrong keys), like Molka's binary benchmark
    ({"damaged": true}). Only used for the 'lenient' damage recall, so the original prompt is not punished twice."""
    m = re.search(r'"(?:visible_damage|damaged|damage)"\s*:\s*(true|false|null)', raw, re.I)
    return {"true": True, "false": False}.get(m.group(1).lower()) if m else None


# ---------------- encoding ----------------
def chat(prompt, image, answer=None):
    msgs = [{"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": prompt}]}]
    if answer is not None:
        msgs.append({"role": "assistant", "content": [{"type": "text", "text": answer}]})
    return msgs


def encode_for_training(processor, image, prompt, answer):
    """Tokenise prompt+answer with the image; labels = -100 everywhere except the answer and its end token.
    The prompt text is the exact chat-template prefix, so its token count is the mask length."""
    prompt_text = processor.apply_chat_template(chat(prompt, image), tokenize=False, add_generation_prompt=True)
    full_text = prompt_text + answer + "<|im_end|>\n"
    full = processor(text=[full_text], images=[image], return_tensors="pt")
    prompt_only = processor(text=[prompt_text], images=[image], return_tensors="pt")
    n_prompt = prompt_only["input_ids"].shape[1]
    ids = full["input_ids"]
    if not (ids[0, :n_prompt] == prompt_only["input_ids"][0]).all():
        raise RuntimeError("prompt is not a prefix of prompt+answer: label mask would be wrong")
    labels = ids.clone()
    labels[:, :n_prompt] = -100
    full["labels"] = labels
    return full


def count_image_tokens(processor, input_ids):
    pad_id = processor.tokenizer.convert_tokens_to_ids("<|image_pad|>")
    return int((input_ids == pad_id).sum())


# ---------------- generation + evaluation ----------------
def generate(model, processor, image, prompt, max_new_tokens=160):
    import torch
    text = processor.apply_chat_template(chat(prompt, image), tokenize=False, add_generation_prompt=True)
    inputs = processor(text=[text], images=[image], return_tensors="pt").to(model.device)
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    t0 = time.perf_counter()
    with torch.no_grad(), _autocast():
        out = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False, temperature=None,
                             top_p=None, top_k=None, use_cache=True)
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    dt = time.perf_counter() - t0
    new = out[0, inputs["input_ids"].shape[1]:]
    return processor.decode(new, skip_special_tokens=True), dt


def predict(model, processor, rows, prompt, log=print, max_new_tokens=160):
    model.eval()   # no dropout while generating (train_run switches back to train mode itself)
    preds = []
    for i, r in enumerate(rows, 1):
        img = open_image(r["image_path"])
        raw, dt = generate(model, processor, img, prompt, max_new_tokens)
        obj, why = parse_output(raw)
        preds.append({"id": r["id"], "raw": raw, "parsed": obj, "parse": why, "latency_s": round(dt, 3)})
        if i % 10 == 0:
            log(f"    {i}/{len(rows)} predicted")
    return preds


def _prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def point_metrics(gold, pred_issue, pred_damage, valid):
    """gold: list of targets. pred_issue: list (None = invalid). Invalid outputs count as wrong."""
    n = len(gold)
    labels = sorted({g["issue_type"] for g in gold})
    acc = sum(p == g["issue_type"] for p, g in zip(pred_issue, gold)) / n
    per = {}
    for c in labels:
        tp = sum(p == c and g["issue_type"] == c for p, g in zip(pred_issue, gold))
        fp = sum(p == c and g["issue_type"] != c for p, g in zip(pred_issue, gold))
        fn = sum(p != c and g["issue_type"] == c for p, g in zip(pred_issue, gold))
        pr, rc, f1 = _prf(tp, fp, fn)
        per[c] = {"precision": pr, "recall": rc, "f1": f1, "support": tp + fn}
    macro_p = sum(v["precision"] for v in per.values()) / len(per)
    macro_r = sum(v["recall"] for v in per.values()) / len(per)
    macro_f1 = sum(v["f1"] for v in per.values()) / len(per)
    # damage = binary task "is there visible damage/dirt?" (gold True vs gold False; gold null rows excluded)
    dmg = [(pd, g["visible_damage"]) for pd, g in zip(pred_damage, gold) if g["visible_damage"] is not None]
    tp = sum(pd is True and gd is True for pd, gd in dmg)
    fn = sum(pd is not True and gd is True for pd, gd in dmg)
    fp = sum(pd is True and gd is False for pd, gd in dmg)
    tn = sum(pd is not True and gd is False for pd, gd in dmg)
    d_p, d_r, d_f = _prf(tp, fp, fn)
    return {"n": n, "accuracy": acc, "macro_precision": macro_p, "macro_recall": macro_r, "macro_f1": macro_f1,
            "damage_recall": d_r, "damage_precision": d_p, "damage_f1": d_f,
            "false_alarm_rate": fp / (fp + tn) if fp + tn else 0.0,
            "json_validity": sum(valid) / n, "per_class": per,
            "damage_confusion": {"tp": tp, "fn": fn, "fp": fp, "tn": tn}}


def metrics(rows, preds, n_boot=2000, seed=42):
    """Point metrics + 95 % bootstrap intervals (resampling photos). Small test set -> wide intervals."""
    gold = [r["target"] for r in rows]
    pi = [p["parsed"]["issue_type"] if p["parsed"] else None for p in preds]
    pdm = [p["parsed"]["visible_damage"] if p["parsed"] else None for p in preds]
    valid = [p["parsed"] is not None for p in preds]
    m = point_metrics(gold, pi, pdm, valid)
    lenient = [lenient_damage(p["raw"]) for p in preds]
    dm = [(ld, g["visible_damage"]) for ld, g in zip(lenient, gold) if g["visible_damage"] is True]
    m["damage_recall_lenient"] = sum(ld is True for ld, _ in dm) / len(dm) if dm else 0.0
    rng = random.Random(seed)
    keys = ["accuracy", "macro_f1", "damage_recall", "json_validity", "false_alarm_rate"]
    boots = {k: [] for k in keys}
    n = len(gold)
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        b = point_metrics([gold[i] for i in idx], [pi[i] for i in idx], [pdm[i] for i in idx], [valid[i] for i in idx])
        for k in keys:
            boots[k].append(b[k])
    m["ci95"] = {k: [sorted(v)[int(0.025 * n_boot)], sorted(v)[int(0.975 * n_boot) - 1]] for k, v in boots.items()}
    lat = sorted(p["latency_s"] for p in preds)
    m["latency_s"] = {"mean": sum(lat) / len(lat), "median": lat[len(lat) // 2],
                      "p95": lat[min(len(lat) - 1, math.ceil(0.95 * len(lat)) - 1)]}
    return m


def paired_bootstrap(rows, preds_a, preds_b, key="issue_type", n_boot=2000, seed=7):
    """P(B better than A) on accuracy by paired resampling of the SAME photos (difference + 95 % interval)."""
    gold = [r["target"][key] for r in rows]
    a = [int(bool(p["parsed"]) and p["parsed"][key] == g) for p, g in zip(preds_a, gold)]
    b = [int(bool(p["parsed"]) and p["parsed"][key] == g) for p, g in zip(preds_b, gold)]
    rng = random.Random(seed)
    n = len(gold)
    diffs = []
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        diffs.append(sum(b[i] - a[i] for i in idx) / n)
    diffs.sort()
    return {"mean_diff": sum(b[i] - a[i] for i in range(n)) / n, "ci95": [diffs[int(0.025 * n_boot)], diffs[int(0.975 * n_boot) - 1]],
            "p_b_better": sum(d > 0 for d in diffs) / n_boot}


# ---------------- training ----------------
def lora_target_regex():
    """LoRA only on the LANGUAGE model linear layers. The vision encoder stays frozen (small data: less
    over-fitting, less memory). The image still drives the loss: the LLM layers read the image tokens."""
    return r".*language_model.*\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)$"


def eval_loss(model, processor, rows, prompt, shuffle_images=False, seed=0):
    """Mean answer-token loss. shuffle_images=True pairs each answer with ANOTHER photo: if the model really
    uses the image, this loss must be clearly higher (image-conditioning check)."""
    import torch
    imgs = [r["image_path"] for r in rows]
    if shuffle_images:
        rng = random.Random(seed)
        imgs = imgs[:]
        while True:
            rng.shuffle(imgs)
            if all(a != r["image_path"] for a, r in zip(imgs, rows)) or len(rows) < 2:
                break
    model.eval()
    tot, cnt = 0.0, 0
    with torch.no_grad():
        for r, ip in zip(rows, imgs):
            batch = encode_for_training(processor, open_image(ip), prompt, answer_text(r["target"])).to(model.device)
            n_tok = int((batch["labels"] != -100).sum())
            with _autocast():
                out = model(**batch)
            tot += float(out.loss) * n_tok
            cnt += n_tok
    return tot / max(cnt, 1)


def train_run(model, processor, train_rows, val_rows, cfg, out_dir, log=print, use_scaler=False, epoch_callback=None):
    """Plain PyTorch loop (no TRL): batch 1 + gradient accumulation, cosine schedule with warm-up,
    answer-only loss, val loss every epoch, adapter saved every epoch, resume from the last saved epoch.
    epoch_callback(epoch, adapter_dir) -> dict of extra validation numbers (e.g. val macro-F1 by generation).
    Early stop: cfg["patience"] epochs in a row without a better val loss."""
    import torch
    from transformers import get_cosine_schedule_with_warmup

    os.makedirs(out_dir, exist_ok=True)
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=cfg["lr"], weight_decay=0.0)
    steps_per_epoch = math.ceil(len(train_rows) / cfg["grad_accum"])
    total = steps_per_epoch * cfg["epochs"]
    sched = get_cosine_schedule_with_warmup(opt, max(1, int(0.1 * total)), total)
    scaler = torch.amp.GradScaler("cuda") if use_scaler else None
    history, start_epoch = [], 0
    state_file = os.path.join(out_dir, "state.pt")
    if os.path.exists(state_file):   # recovery after an interruption
        st = torch.load(state_file, map_location="cpu", weights_only=False)
        from peft import set_peft_model_state_dict
        set_peft_model_state_dict(model, st["adapter"])
        opt.load_state_dict(st["opt"])
        sched.load_state_dict(st["sched"])
        history, start_epoch = st["history"], st["epoch"] + 1
        log(f"  resumed {out_dir} after epoch {st['epoch'] + 1}")
    rng = random.Random(cfg["seed"])
    order = list(range(len(train_rows)))
    for epoch in range(start_epoch, cfg["epochs"]):
        model.train()
        rng_epoch = random.Random(cfg["seed"] * 1000 + epoch)
        rng_epoch.shuffle(order)
        run_loss, run_n, t0 = 0.0, 0, time.time()
        opt.zero_grad(set_to_none=True)
        for k, idx in enumerate(order, 1):
            r = train_rows[idx]
            batch = encode_for_training(processor, open_image(r["image_path"]), cfg["prompt"],
                                        answer_text(r["target"])).to(model.device)
            with _autocast():
                loss = model(**batch).loss / cfg["grad_accum"]
            if not torch.isfinite(loss):
                raise FloatingPointError(f"non-finite loss at epoch {epoch + 1}, example {r['id']}")
            (scaler.scale(loss) if scaler else loss).backward()
            run_loss += float(loss) * cfg["grad_accum"]
            run_n += 1
            if k % cfg["grad_accum"] == 0 or k == len(order):
                if scaler:
                    scaler.unscale_(opt)
                gn = torch.nn.utils.clip_grad_norm_(params, 1.0)
                if scaler:
                    scaler.step(opt)
                    scaler.update()
                else:
                    opt.step()
                sched.step()
                opt.zero_grad(set_to_none=True)
        tr = run_loss / run_n
        vl = eval_loss(model, processor, val_rows, cfg["prompt"])
        mem = torch.cuda.max_memory_allocated() / 2**30 if torch.cuda.is_available() else 0.0
        rec = {"epoch": epoch + 1, "train_loss": tr, "val_loss": vl, "last_grad_norm": float(gn),
               "lr": sched.get_last_lr()[0], "seconds": round(time.time() - t0, 1), "max_gpu_mem_gb": round(mem, 2)}
        log(f"  epoch {epoch + 1}: train_loss {tr:.4f}  val_loss {vl:.4f}  grad_norm {float(gn):.3f}  "
            f"{rec['seconds']} s  peak GPU {rec['max_gpu_mem_gb']} GB")
        ep_dir = os.path.join(out_dir, f"epoch_{epoch + 1}")
        model.save_pretrained(ep_dir)
        if epoch_callback:
            rec.update(epoch_callback(epoch + 1, ep_dir))
            model.train()
        history.append(rec)
        from peft import get_peft_model_state_dict
        torch.save({"adapter": get_peft_model_state_dict(model), "opt": opt.state_dict(), "sched": sched.state_dict(),
                    "history": history, "epoch": epoch}, state_file)
        best_vl = min(h["val_loss"] for h in history)
        since_best = len(history) - 1 - [h["val_loss"] for h in history].index(best_vl)
        if cfg.get("patience") and since_best >= cfg["patience"]:
            log(f"  early stop: val loss has not improved for {since_best} epoch(s)")
            break
    return history


def load_adapter_weights(model, adapter_dir):
    """Put the LoRA weights saved in adapter_dir into the (same-shape) PEFT model."""
    from peft import set_peft_model_state_dict
    from safetensors.torch import load_file
    set_peft_model_state_dict(model, load_file(os.path.join(adapter_dir, "adapter_model.safetensors")))
