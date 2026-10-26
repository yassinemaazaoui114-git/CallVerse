"""CPU satisfaction scorer: fine-tuned MiniLM (all-MiniLM-L12-v2) exported to ONNX int8, ~10 ms per score.
Weights are not in git: put scorer_int8.onnx + tokenizer.json in `scorer.model_dir` (see SIMULATOR_README.md)."""
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
DELAY = [(5, "0-5 min"), (30, "5-30 min"), (120, "30 min-2 h"), (480, "2-8 h"), (float("inf"), "8 h+")]


def wait_bucket(m):
    if m is None or m < 0:
        return "n/a"
    return next(lab for hi, lab in DELAY if m <= hi)


def scorer_text(role_card, transcript, source_tag="csat"):
    """Same layout as the training rows: '[source] reason: .. | wait/lateness: .. | turns: .. | text'."""
    turns = sum(1 for t in transcript if t["role"] == "customer")
    body = " ".join(("U: " if t["role"] == "customer" else "A: ") + t["text"] for t in transcript)
    return (f"[{source_tag}] reason: {role_card.get('reason', 'other')} | wait/lateness: {wait_bucket(role_card.get('wait_minutes'))} "
            f"| turns: {turns} | {body}")[-2000:]


class OnnxScorer:
    def __init__(self, model_dir, model_file="scorer_int8.onnx", calibration_file=None, source_tag="csat", maxlen=256,
                 calibration="dev"):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        d = Path(model_dir)
        if not d.is_absolute():
            d = HERE.parent / d
        self.tok = Tokenizer.from_file(str(d / "tokenizer.json"))
        self.tok.enable_truncation(maxlen)
        self.tok.enable_padding()
        self.sess = ort.InferenceSession(str(d / model_file), providers=["CPUExecutionProvider"])
        self.source_tag = source_tag
        cal = json.loads((HERE / calibration_file).read_text()) if calibration_file else {}
        c = cal.get(source_tag, {})
        # "dev" = the map chosen on dev for this source; "isotonic" / "quantile" (distribution matching) / "none" = forced
        method = c.get("method", "none") if calibration == "dev" else calibration
        mp = c.get(f"{method}_map") if method in ("isotonic", "quantile") else None
        self.iso = {"x": mp[0], "y": mp[1]} if mp else None
        self.method = method if mp else "none"

    def raw(self, texts):
        e = self.tok.encode_batch(list(texts))
        ids = np.array([x.ids for x in e], dtype=np.int64)
        att = np.array([x.attention_mask for x in e], dtype=np.int64)
        return np.clip(self.sess.run(None, {"input_ids": ids, "attention_mask": att})[0].reshape(-1) * 2 + 3, 1, 5)

    def __call__(self, role_card, transcript):
        r = float(self.raw([scorer_text(role_card, transcript, self.source_tag)])[0])
        e = float(np.interp(r, self.iso["x"], self.iso["y"])) if self.iso else r
        return r, e
