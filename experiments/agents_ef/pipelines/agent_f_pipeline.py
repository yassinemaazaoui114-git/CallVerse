"""Reproducible Agent F pipeline: data -> subset -> fine-tune -> checkpoint OUTSIDE git -> manifest -> verification.

    python -m pipelines.agent_f_pipeline --work <folder outside git> [--device cuda --fp16] [--seeds 0 1 2]
Reproduces the validated model of REPORT_v2 §6: multilingual-e5-small (revision pinned), vocabulary trimmed to
the tokens of an unlabelled EN/FR/PT corpus, fine-tuned on genuine 1-5 star ratings (EN+FR), best seed by VAL.
Steps (each one is skipped if its output already exists and its SHA256 matches):
  1. download the 4 Amazon EN/FR jsonl files (5.3 MB) and the Olist zip (44.7 MB); check SHA256
  2. Olist 1,000-review subset (its TRAIN texts are part of the unlabelled vocabulary corpus); check SHA256
  3. EN/FR 2,000-review subset (TRAIN 1,200 / VAL 400 / TEST 399); check SHA256
  4. fine-tune (real_data/eval_f_v2.py, same arguments as the validated run) -> <work>/checkpoints/
  5. manifest.json: data hashes, checkpoint hash, metrics, library versions, git commit
  6. verify: reload the checkpoint through integration/agent_f_predictor.py, re-score TEST, compare with step 4
Bit-identical weights are only expected on the same CPU / thread count / library versions; across machines (or on
GPU) expect TEST MAE within the seed spread (0.630 +- 0.007 on CPU). Raw texts stay in <work>, never in git.
"""

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

AMAZON = "https://huggingface.co/datasets/mteb/amazon_reviews_multi/resolve/main/{lang}/{split}.jsonl"
OLIST = "https://www.kaggle.com/api/v1/datasets/download/olistbr/brazilian-ecommerce"
SHA = {  # recorded on 2026-10-23 from the files the validated checkpoint was trained on
    "amazon/en_validation.jsonl": "715498d7f42d96548754a862984a90fa33522a2f9a4b844df58f4e9b821e7848",
    "amazon/en_test.jsonl": "a18f5860ed40a89a2d2af4a0d1ed300394560ae61e414158009c1d781f2cce03",
    "amazon/fr_validation.jsonl": "fa9089ddad304890d842284fa32e17b64f61ae03713483a33e1ac1a8d31c82ac",
    "amazon/fr_test.jsonl": "cc8a56cb3c7bbb05671573d06dd7ae01cafff2f329a866b0b7749a64069ad5ea",
    "olist/raw/olist_order_reviews_dataset.csv": "012b61c7593e34f51fa614efdf802b9c7056ce6aae5307ddb93236e7cfc797d7",
    "olist/subset/train.jsonl": "2779866e92559fdd2f83857778bd98662a672ecbaa56e62eb530d14ab96a2833",
    "enfr/train.jsonl": "20d7cc86e6efbb575bfeae41d29f60c0a739720856069dd6aacae537e841f64a",
    "enfr/val.jsonl": "69b86b6d4e80c5814d416d404b8102e924761942ace46ae8a215e87e29b5aa75",
    "enfr/test.jsonl": "2c7bc9be79da8cb421b4e22cee17ee136115bfe932c394620c56d1ebd3ab0384",
}
REFERENCE = {"checkpoint_sha256_cpu_2threads": "6bae1f48b244b4ec40e1893940a713ba429bfb9080683b0ebc3fce06586aa22e",
             "test_mae_mean_3seeds": 0.630, "test_mae_std": 0.007, "best_seed": 0}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check(work: Path, rel: str, strict: bool):
    got = sha256(work / rel)
    ok = got == SHA[rel]
    print(f"  {'OK ' if ok else 'DIFF'} {rel} {got[:16]}")
    if not ok and strict:
        raise SystemExit(f"SHA256 mismatch for {rel}: the data changed; rerun with --no-strict to continue anyway")
    return {"sha256": got, "matches_reference": ok}


def fetch(url: str, dst: Path):
    if dst.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    print(f"  downloading {url}")
    urllib.request.urlretrieve(url, dst)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True, help="folder OUTSIDE git for data and checkpoints")
    ap.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--fp16", action="store_true")
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--no-strict", dest="strict", action="store_false")
    a = ap.parse_args(argv)
    work = Path(a.work).resolve()
    if HERE.parent.parent in work.parents or work == HERE.parent.parent:
        raise SystemExit("--work must be OUTSIDE the git repository (raw texts and weights never go to git)")
    man = {"data": {}}
    print("1. data")
    for lang in ("en", "fr"):
        for split in ("validation", "test"):
            fetch(AMAZON.format(lang=lang, split=split), work / "amazon" / f"{lang}_{split}.jsonl")
            man["data"][f"amazon/{lang}_{split}.jsonl"] = check(work, f"amazon/{lang}_{split}.jsonl", a.strict)
    if not (work / "olist/raw/olist_order_reviews_dataset.csv").exists():
        fetch(OLIST, work / "olist" / "olist.zip")
        zipfile.ZipFile(work / "olist" / "olist.zip").extractall(work / "olist" / "raw")
    man["data"]["olist/raw/olist_order_reviews_dataset.csv"] = check(work, "olist/raw/olist_order_reviews_dataset.csv",
                                                                     a.strict)
    print("2. Olist subset (vocabulary corpus)")
    from real_data import build_reviews_subset, eval_f_v2, prepare_subset
    if not (work / "olist/subset/train.jsonl").exists():
        prepare_subset.main(["--input", str(work / "olist/raw/olist_order_reviews_dataset.csv"),
                             "--text", "review_comment_message", "--rating", "review_score", "--conv-id", "order_id",
                             "--id-col", "review_id", "--lang-value", "pt", "--n", "1000", "--seed", "0",
                             "--out", str(work / "olist/subset")])
    man["data"]["olist/subset/train.jsonl"] = check(work, "olist/subset/train.jsonl", a.strict)
    print("3. EN/FR subset")
    if not (work / "enfr/test.jsonl").exists():
        build_reviews_subset.main(["--raw", str(work / "amazon"), "--per-lang", "1000", "--out", str(work / "enfr")])
    for s in ("train", "val", "test"):
        man["data"][f"enfr/{s}.jsonl"] = check(work, f"enfr/{s}.jsonl", a.strict)
    print("4. fine-tune e5small_trim_ft")
    vc = [str(work / "amazon/en_validation.jsonl"), str(work / "amazon/fr_validation.jsonl"),
          str(work / "olist/subset/train.jsonl")]
    args = ["--data", str(work / "enfr"), "--model", "e5small_trim_ft", "--seeds", *map(str, a.seeds),
            "--threads", str(a.threads), "--vocab-corpus", *vc, "--save-dir", str(work / "checkpoints"),
            "--out", str(work / "results"), "--label", "Agent F pipeline (EN/FR genuine stars)", "--device", a.device]
    if a.fp16:
        args.append("--fp16")
    eval_f_v2.main(args)
    res = json.loads((work / "results" / "e5small_trim_ft.json").read_text())
    best = res["best_seed_by_val"]
    ck = work / "checkpoints" / f"e5small_trim_ft_s{best}"
    print("5. manifest")
    import torch
    import transformers
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=HERE, text=True).strip()
    except Exception:
        commit = None
    man.update({"best_seed_by_val": best, "checkpoint": str(ck), "checkpoint_sha256": sha256(ck / "model.pt"),
                "checkpoint_matches_reference_bitwise": sha256(ck / "model.pt") == REFERENCE["checkpoint_sha256_cpu_2threads"],
                "test_mean": res["test_mean"], "test_std": res["test_std"], "reference": REFERENCE,
                "versions": {"python": sys.version.split()[0], "torch": torch.__version__,
                             "transformers": transformers.__version__, "platform": platform.platform(),
                             "device": a.device, "fp16": a.fp16, "threads": a.threads}, "git_commit": commit})
    print("6. verify (reload through the integration interface, re-score TEST)")
    from integration.agent_f_predictor import SatisfactionPredictor
    f = SatisfactionPredictor.load(ck, device=a.device)
    test = [json.loads(line) for line in open(work / "enfr" / "test.jsonl", encoding="utf-8")]
    pred = np.array([p["score"] for p in f.predict([r["text"] for r in test])])
    y = np.array([r["rating"] for r in test])
    mae = float(np.abs(pred - y).mean())
    run = next(r for r in res["runs"] if r["seed"] == best)
    man["verify"] = {"reloaded_test_mae": mae, "training_run_test_mae": run["test"]["all"]["mae"],
                     "same": abs(mae - run["test"]["all"]["mae"]) < 1e-3,
                     "within_reference_spread": abs(res["test_mean"]["all"]["mae"] - REFERENCE["test_mae_mean_3seeds"])
                     <= 3 * REFERENCE["test_mae_std"] + 0.01}
    (work / "manifest.json").write_text(json.dumps(man, indent=2))
    print(json.dumps(man["verify"], indent=1), "\nmanifest:", work / "manifest.json")
    return man


if __name__ == "__main__":
    main()
