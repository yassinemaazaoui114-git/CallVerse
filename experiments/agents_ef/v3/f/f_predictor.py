"""Agent F v3 predictor: support dialogue text -> predicted satisfaction (1-5) + class.

v3 copy of integration/agent_f_predictor.py (that file is not edited). The differences:
  - handles layer-truncated encoders (meta.json "layers");
  - truncates from the LEFT (keeps the end of the dialogue, as in training);
  - can load the int8 dynamically-quantized checkpoint (model_int8.pt, made by quantize_f.py).

    f = SatisfactionPredictor.load("<f_v3/ckpt/<tag>_s<seed>>")
    f.predict(["Customer: my parcel is late\nAgent: it was delivered today\nCustomer: thanks!"])
Output is advice (Agent E reward / reporting); Agent F never acts.
"""

import json
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))     # experiments/agents_ef
from real_data.eval_f_v2 import Reg  # noqa: E402


def label(score: float) -> str:
    return "unhappy" if score < 2.5 else "neutral" if score < 3.5 else "happy"


def build_model(ckpt_dir):
    """Rebuild the architecture from meta.json + the saved state dict shapes (fp32 weights loaded)."""
    from transformers import AutoConfig, AutoModel
    ckpt_dir = Path(ckpt_dir)
    meta = json.loads((ckpt_dir / "meta.json").read_text())
    state = torch.load(ckpt_dir / "model.pt", map_location="cpu", weights_only=False)
    cfg = AutoConfig.from_pretrained(meta["base_model"], revision=meta.get("revision"))
    if meta.get("layers"):
        cfg.num_hidden_layers = int(meta["layers"])          # layer-truncated encoder
    bert = AutoModel.from_config(cfg)
    n_vocab = state["bert.embeddings.word_embeddings.weight"].shape[0]
    if n_vocab != cfg.vocab_size:                               # trimmed vocabulary
        emb = bert.get_input_embeddings()
        bert.set_input_embeddings(nn.Embedding(n_vocab, emb.embedding_dim, padding_idx=emb.padding_idx))
        bert.config.vocab_size = n_vocab
    remap = state.get("remap")
    model = Reg(bert, remap if remap is not None and remap.numel() else None)
    model.load_state_dict(state)
    return model.eval(), meta


def quantize(model):
    """Post-training dynamic int8 quantization of every nn.Linear (weights int8, activations quantized on the fly)."""
    return torch.ao.quantization.quantize_dynamic(model, {nn.Linear}, dtype=torch.qint8)


class SatisfactionPredictor:
    def __init__(self, model, tok, meta):
        self.model, self.tok, self.meta = model.eval(), tok, meta

    @classmethod
    def load(cls, ckpt_dir, int8=False):
        from transformers import AutoTokenizer
        model, meta = build_model(ckpt_dir)
        if int8:
            model = quantize(model)
            q = Path(ckpt_dir) / "model_int8.pt"
            if q.exists():                                      # the saved int8 weights (same result, smaller file)
                model.load_state_dict(torch.load(q, map_location="cpu", weights_only=False))
        tok = AutoTokenizer.from_pretrained(meta["base_model"], revision=meta.get("revision"))
        tok.truncation_side = meta.get("truncation_side", "right")     # v2 checkpoints (no key) used right
        return cls(model, tok, meta)

    @torch.no_grad()
    def scores(self, texts, batch=16):
        pre, out = self.meta.get("prefix", ""), []
        for i in range(0, len(texts), batch):
            b = self.tok([pre + t for t in texts[i:i + batch]], padding=True, truncation=True,
                         max_length=self.meta.get("max_length", 256), return_tensors="pt")
            out.append(self.model(b["input_ids"], b["attention_mask"]).float().numpy())
        return np.clip(np.concatenate(out), 1, 5)

    def predict(self, texts):
        return [{"score": round(float(s), 3), "label": label(float(s))} for s in self.scores(texts)]
