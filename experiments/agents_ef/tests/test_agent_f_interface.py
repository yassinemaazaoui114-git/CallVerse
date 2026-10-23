"""Agent F interface: a vocabulary-trimmed multilingual checkpoint reloads and predicts the same scores (EN + FR)."""

import json

import pytest
import torch

pytest.importorskip("transformers")


def test_trimmed_checkpoint_round_trip(tmp_path):
    from transformers import AutoModel, AutoTokenizer
    from integration.agent_f_predictor import SatisfactionPredictor
    from real_data.eval_f_v2 import ENC, Reg, build_remap, trim_model
    name = ENC["e5small"]
    try:
        tok, bert = AutoTokenizer.from_pretrained(name), AutoModel.from_pretrained(name)
    except Exception:
        pytest.skip("model not cached (offline)")
    texts = ["query: The parcel never arrived, terrible.", "query: Très bon produit, livraison rapide, merci !"]
    kept, remap = build_remap(tok, texts + ["query: some other words for the vocabulary"])
    model = Reg(trim_model(bert, kept), remap).eval()
    assert model.bert.config.vocab_size == len(kept) < 1000
    torch.save(model.state_dict(), tmp_path / "model.pt")
    (tmp_path / "meta.json").write_text(json.dumps({"base_model": name, "prefix": "query: ", "max_length": 128}))
    f = SatisfactionPredictor.load(tmp_path)
    got = f.predict([t[len("query: "):] for t in texts])
    with torch.no_grad():
        b = tok(texts, padding=True, return_tensors="pt")
        ref = model(b["input_ids"], b["attention_mask"]).numpy()
    for g, r in zip(got, ref):
        assert g["score"] == pytest.approx(min(max(float(r), 1), 5), abs=1e-3)
        assert g["label"] in ("unhappy", "neutral", "happy")
