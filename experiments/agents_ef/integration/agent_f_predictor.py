"""Integration-ready Agent F: conversation text -> predicted satisfaction (1-5) + class (research branch only).

    f = SatisfactionPredictor.load("<checkpoint folder from real_data/eval_f_v2.py --save-dir>")
    f.predict(["Merci, le remboursement est arrivé.", "Still no parcel after 3 weeks!"])
    -> [{"score": 4.4, "label": "happy"}, {"score": 1.6, "label": "unhappy"}]
The checkpoint holds the encoder (vocabulary possibly trimmed: the old->new token map is saved with it), the
regression head and meta.json (base model, prefix, max length). Satisfaction is NOT sentiment: the model was
fine-tuned on genuine 1-5 customer ratings. Output is advice for Agent E's reward / reporting; F never acts.
"""

import json
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from real_data.eval_f_v2 import Reg  # noqa: E402


def label(score: float) -> str:
    return "unhappy" if score < 2.5 else "neutral" if score < 3.5 else "happy"


class SatisfactionPredictor:
    def __init__(self, model, tok, meta, device="cpu"):
        self.model, self.tok, self.meta, self.dev = model.eval(), tok, meta, torch.device(device)

    @classmethod
    def load(cls, ckpt_dir, device="cpu"):
        from transformers import AutoConfig, AutoModel, AutoTokenizer
        ckpt_dir = Path(ckpt_dir)
        meta = json.loads((ckpt_dir / "meta.json").read_text())
        state = torch.load(ckpt_dir / "model.pt", map_location="cpu", weights_only=False)
        cfg = AutoConfig.from_pretrained(meta["base_model"])
        bert = AutoModel.from_config(cfg)
        n_vocab = state["bert.embeddings.word_embeddings.weight"].shape[0]
        if n_vocab != cfg.vocab_size:                                   # trimmed vocabulary
            emb = bert.get_input_embeddings()
            bert.set_input_embeddings(nn.Embedding(n_vocab, emb.embedding_dim, padding_idx=emb.padding_idx))
            bert.config.vocab_size = n_vocab
        remap = state.get("remap")
        model = Reg(bert, remap if remap is not None and remap.numel() else None)
        model.load_state_dict(state)
        return cls(model.to(device), AutoTokenizer.from_pretrained(meta["base_model"]), meta, device)

    @torch.no_grad()
    def predict(self, texts: list[str], batch: int = 32) -> list[dict]:
        pre, out = self.meta.get("prefix", ""), []
        for i in range(0, len(texts), batch):
            b = self.tok([pre + t for t in texts[i:i + batch]], padding=True, truncation=True,
                         max_length=self.meta.get("max_length", 128), return_tensors="pt")
            s = self.model(b["input_ids"].to(self.dev), b["attention_mask"].to(self.dev)).float().cpu().numpy()
            out += [{"score": round(float(np.clip(x, 1, 5)), 3), "label": label(float(np.clip(x, 1, 5)))} for x in s]
        return out
