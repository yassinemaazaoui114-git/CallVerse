"""Manual CPU check of the training code with the REAL Qwen3-VL-2B weights (no GPU, no 4-bit).

Run:  python cpu_smoke_check.py --model <folder or Qwen/Qwen3-VL-2B-Instruct> --data <built dataset folder>
It proves on 3 photos that: LoRA sits only on the language model, only answer tokens carry loss, the LoRA
weights get non-zero gradients, the loss falls after a few steps, the loss rises when the photos are swapped
(the model really reads the image), and generation + JSON parsing run. It is NOT a GPU or 4-bit test.
"""
import argparse, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import torch
import cv_vision_lib as L
from transformers import AutoProcessor, Qwen3VLForConditionalGeneration
from peft import LoraConfig, get_peft_model

ap = argparse.ArgumentParser()
ap.add_argument("--model", required=True)
ap.add_argument("--data", required=True)
a = ap.parse_args()
torch.manual_seed(42)
proc = AutoProcessor.from_pretrained(a.model)
proc.image_processor.size = {"longest_edge": 256 * 256, "shortest_edge": 128 * 128}   # small = fast on CPU
model = Qwen3VLForConditionalGeneration.from_pretrained(a.model, dtype=torch.float32)
model.config.use_cache = False
lcfg = LoraConfig(r=16, lora_alpha=32, lora_dropout=0.0, target_modules=L.lora_target_regex(), task_type="CAUSAL_LM")
model = get_peft_model(model, lcfg)
names = [n for n, p in model.named_parameters() if p.requires_grad]
report = {"trainable_tensors": len(names),
          "trainable_params": sum(p.numel() for p in model.parameters() if p.requires_grad),
          "lora_in_vision_tower": sum("visual" in n for n in names)}
rows = [r for r in L.load_rows(a.data) if r["split"] == "train"][:3]
b = L.encode_for_training(proc, L.open_image(rows[0]["image_path"]), L.PROMPT_IMPROVED, L.answer_text(rows[0]["target"]))
report["image_tokens"] = L.count_image_tokens(proc, b["input_ids"])
report["answer_tokens"] = int((b["labels"] != -100).sum())
model.train()
opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=1e-3)
losses = []
for step in range(4):
    out = model(**b)
    out.loss.backward()
    if step == 0:
        g = [p.grad.abs().sum().item() for n, p in model.named_parameters() if p.requires_grad and p.grad is not None]
        report["lora_tensors_with_nonzero_grad"] = sum(x > 0 for x in g)
    opt.step(); opt.zero_grad()
    losses.append(round(float(out.loss), 4))
report["loss_same_example_4_steps"] = losses
report["loss_real_images"] = round(L.eval_loss(model, proc, rows, L.PROMPT_IMPROVED), 4)
report["loss_swapped_images"] = round(L.eval_loss(model, proc, rows, L.PROMPT_IMPROVED, shuffle_images=True), 4)
model.eval()
t = time.time()
raw, dt = L.generate(model, proc, L.open_image(rows[0]["image_path"]), L.PROMPT_IMPROVED, max_new_tokens=80)
report["generation_seconds_cpu"] = round(dt, 1)
report["generation_text"] = raw
report["parse"] = L.parse_output(raw)[1]
print(json.dumps(report, indent=1))
