# Vision QLoRA (Qwen3-VL-2B) — dataset + Kaggle notebook

Kept apart from the running system (like `benchmarks/m3/`). Nothing here is used by CallVerse yet: the adapter is
integrated only after the Kaggle results are reviewed.

## In plain words
A customer can send a photo. The photo model says only **what it can see** (cracked screen, torn box, broken
suitcase, dirty room, nothing wrong, or "cannot tell"), as one fixed JSON object. It never guesses what the
customer wants: that comes from the text (Intake). The two are joined later ("late fusion"), and only the
Coordinator's rules decide anything. This folder builds a small set of 150 **real** photos and a Kaggle
notebook that measures the original Qwen3-VL-2B and fine-tunes it (QLoRA) to answer in that format reliably.

## Files
| File | What it is |
|---|---|
| `manifest.jsonl` | the 150 photos: source, pinned revision, sha256, visual label, description, written customer message |
| `build_dataset.py` | downloads the photos again, checks sha256, normalises, quality + duplicate checks, group split |
| `cv_vision_lib.py` | prompts, JSON parser, label masking, metrics (bootstrap 95 % intervals), training loop |
| `make_notebook.py` | writes the notebook from the 3 files above (keeps them in sync; a test checks it) |
| `CallVerse_Qwen3VL_QLoRA_Training.ipynb` | **the Kaggle notebook** (self-contained) |
| `local_smoke_test.py` | CPU check of the training code with the real model weights (no GPU) |
| `DATASET_PROVENANCE.md` | sources, licences, real/synthetic counts, what was rejected and why |

## Run on Kaggle (the only manual step)
1. Kaggle → **Create → New Notebook → File → Import Notebook** → upload `CallVerse_Qwen3VL_QLoRA_Training.ipynb`.
2. Right panel → **Session options**: Accelerator **GPU T4 x2** (P100 also works); **Internet: On**
   (needed to download the photos and the model; a phone-verified Kaggle account is required for both).
3. **Run All**. Expected time on one T4: about 1-1.5 h (3 training runs). No data to attach, no cell to edit.
4. Output panel → download **`callverse_vision_qlora_results.zip`** (adapter + metrics + plots, ~70-140 MB).

If the internet cannot be switched on: run `python build_dataset.py --out callverse_vision_dataset` on any PC,
zip the folder, upload it as a **private** Kaggle Dataset and attach it; the notebook finds `dataset.jsonl` there
(do not make it public: see the licence notes).

## Dataset (built 2026-11-01)
150 real photos, 0 synthetic. ShopNova 56, Atlas 94. 129 groups (same suitcase / box / hotel / room together).
Split by group, stratified, seed 42: **train 103 / val 22 / test 25**. Every class is in every split.

| issue_type (visual evidence) | train | val | test |
|---|---:|---:|---:|
| cracked_screen | 12 | 2 | 2 |
| screen_display_defect | 3 | 1 | 1 |
| damaged_packaging | 5 | 1 | 2 |
| damaged_luggage | 14 | 3 | 3 |
| dirty_or_messy_room | 10 | 2 | 2 |
| damaged_room_fixture | 10 | 2 | 4 |
| no_visible_issue | 43 | 9 | 9 |
| unclear | 6 | 2 | 2 |

Checks run by the builder (numbers from the local build): 150/150 sha256 match, 0 decode errors, 0 exact
duplicates, 0 near-duplicate pairs at dHash ≤ 6 (closest cross-split pair: distance 11, two different photos),
0 label problems, 0 groups in two splits, 20 rows in `review_queue.csv` (10 "unclear by design", 6 blurry,
4 images under 256 px). Customer contact reasons (written messages) cover all 15 company reasons
(ShopNova 7, Atlas 8) + 17 image-only cases.

## Output the model learns
```json
{"visible_damage": true, "object": "smartphone", "issue_type": "cracked_screen",
 "description": "A black smartphone in a case shows a shattered screen with many cracks.",
 "confidence_level": "high", "requires_review": true}
```
`visible_damage` = `null` when the photo does not allow a decision. `requires_review` = true for any damage or
doubt. No intent, emotion, order, booking, payment or decision field exists, so the model cannot output one.

## What was checked here, and what was not
- Checked on CPU with the real Qwen3-VL-2B weights (`local_smoke_test.py`): LoRA only on the language model
  (17.4 M parameters, 0 in the vision encoder); only the answer tokens carry loss; LoRA gets gradients; loss
  drops on a repeated example; loss is higher with swapped photos (the image is really used); generation + parser.
- Checked on CPU: the whole notebook (all 10 cells) in a dry run with fp32, no 4-bit, tiny subsets.
- **Not** checked: a GPU run, 4-bit (bitsandbytes needs CUDA), fp16 behaviour, real timings. The notebook has
  fall-backs for these (4-bit load fails → 16-bit LoRA; NaN loss in fp16 → fp32 compute).

## Limits (honest)
- 25 test photos: a difference of one photo = 4 points of accuracy. Read the 95 % intervals, not the point value.
- Room photos: one mobile home (not a hotel) gives all "dirty" rooms; clean rooms come from Hotels-50K. A model
  can partly learn "hotel look = clean". Wall cracks come from earthquake-damaged buildings.
- Gaps (no usable real photos): torn clothing, missing parts, missing hotel amenities, "room differs from the
  advert". "Wrong item" cannot be seen in a photo alone: the photo gives the object, the order data says what was
  bought — that comparison belongs to the agents' tools, not to the vision model.
- Licences: see `DATASET_PROVENANCE.md` (60 photos are research-only / no licence: not redistributed).
