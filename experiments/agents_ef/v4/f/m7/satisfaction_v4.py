"""M7 v4 responsibility 1: a satisfaction score for every closed conversation, WITH its validity.

    scorer = load_scorer_v4("tfidf:<dir>" | "f:<dir>" | "none")
    records = score_with_validity(convs, scorer, card)     # one record per conversation

Why v4: V3 gave every conversation a bare number. The number came from a model trained on third-party annotator
judgements of other dialogues (USS), in English and Chinese, and it was shown for French conversations too, as
if it meant the same thing. v4 attaches to every score what it is and how far it can be trusted:

  model_id, model_sha256    which model produced it (the file is checked when loaded)
  label_type                what the model learned to predict (e.g. human_annotation, NOT customer ratings)
  language                  detected language of the CLIENT's message (en / fr / ar / zh / unknown)
  language_validated        was the model measured on labelled dialogues in that language?
  domain_validated          was it measured on labelled CallVerse/ShopNova conversations? (card["corpus"])
  validity                  one value per conversation:
     validated                       language and domain validated -> may feed KPIs (and E, if the gate passes)
     indicative_out_of_domain        language validated, domain not -> shown only as "indicative, not validated"
     withheld_language_not_validated score NOT given (predicted_satisfaction = None); French falls here today
     no_score                        no model configured
  usable_for                ["kpi"] / ["kpi_indicative"] / []
French is never silently scored: with the default `score_unvalidated_languages=False` it gets no number.
"""

import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))          # experiments/agents_ef
from v3.m7.conversations import dialogue_text  # noqa: E402

FR_WORDS = re.compile(r"\b(bonjour|commande|je|vous|ma|mon|est|pas|merci|livr\w*|rembours\w*|retard|où|quand|"
                      r"s'il|svp|colis|reçu|toujours|cassé\w*)\b", re.I)
FR_CHARS = re.compile(r"[éèêàùçôîœ]", re.I)
ARABIC = re.compile(r"[؀-ۿ]")
CJK = re.compile(r"[一-鿿]")
LATIN = re.compile(r"[a-z]", re.I)
# Languages each saved scorer was MEASURED on, with labelled dialogues (v3/f results). Product-review stars
# (Amazon FR) are a different label and task, so they do not validate French dialogue satisfaction.
LANGS_VALIDATED = {"tfidf_ridge_tail256": ["en", "zh"], "e5small_trim_ft_L6_frac0.5_len256": ["en", "zh"],
                   "tinybert_ft_en_frac0.5_len128": ["en"]}
USS_MEDIAN_TURNS = 25           # USS TEST median turns (v4/f/results/f1_diagnosis.json, structure.uss_test_all)


def detect_language(text: str) -> str:
    """Tiny rule-based detector for the client message (CallVerse languages: French, Arabic, English)."""
    t = text or ""
    if len(ARABIC.findall(t)) >= 3:
        return "ar"
    if len(CJK.findall(t)) >= 3:
        return "zh"
    fr = len(FR_WORDS.findall(t))
    if fr >= 2 or (fr >= 1 and FR_CHARS.search(t)):
        return "fr"
    return "en" if len(LATIN.findall(t)) >= 3 else "unknown"


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Scorer:
    """A loaded satisfaction model + its identity."""

    def __init__(self, model, model_id, sha256, meta):
        self.model, self.model_id, self.sha256, self.meta = model, model_id, sha256, meta

    def scores(self, texts):
        return [float(x) for x in self.model.scores(texts)]


def load_scorer_v4(spec: str | None):
    if spec in (None, "", "none"):
        return None
    kind, _, path = spec.partition(":")
    path = Path(path)
    meta = json.loads((path / "meta.json").read_text())
    if kind == "tfidf":
        from v4.f.tfidf_predictor import TfidfSatisfactionPredictor
        model = TfidfSatisfactionPredictor.load(path)           # verifies SHA256 before unpickling
        return Scorer(model, meta["model"], meta["sha256"], meta)
    if kind == "f":
        from v3.f.f_predictor import SatisfactionPredictor
        model = SatisfactionPredictor.load(path)
        name = path.name.rsplit("_s", 1)[0]
        return Scorer(model, path.name, _sha(path / "model.pt"), {**meta, "model": name})
    raise ValueError(f"unknown scorer spec {spec!r}: use tfidf:<dir>, f:<dir> or none")


def languages_validated(scorer) -> list[str]:
    if scorer is None:
        return []
    return scorer.meta.get("languages_validated") or LANGS_VALIDATED.get(scorer.meta.get("model"), [])


def score_with_validity(convs: list[dict], scorer, card: dict | None = None,
                        score_unvalidated_languages: bool = False) -> list[dict]:
    langs_ok = languages_validated(scorer)
    domain_ok = bool(card and card.get("corpus") == "callverse" and card.get("domain") == "support_conversation")
    texts = [dialogue_text(c) for c in convs]
    langs = [detect_language(c.get("client_text") or "") for c in convs]
    todo = [i for i, lg in enumerate(langs) if scorer is not None and (lg in langs_ok or score_unvalidated_languages)]
    raw = dict(zip(todo, scorer.scores([texts[i] for i in todo]))) if todo else {}
    out = []
    for i, c in enumerate(convs):
        lg = langs[i]
        rec = {"conversation_id": c["conversation_id"], "language": lg, "language_validated": lg in langs_ok,
               "languages_validated": langs_ok, "domain_validated": domain_ok,
               "model_id": scorer.model_id if scorer else None, "model_sha256": scorer.sha256 if scorer else None,
               "label_type": (scorer.meta.get("label_type") if scorer else None) or
               ("human_annotation (USS third-party annotators)" if scorer else None),
               "input_turns": len([x for x in texts[i].split("\n") if x.strip()]),
               "training_median_turns": USS_MEDIAN_TURNS if scorer else None}
        reasons = []
        if scorer is None:
            validity, score = "no_score", None
            reasons.append("no satisfaction model configured")
        elif lg not in langs_ok and not score_unvalidated_languages:
            validity, score = "withheld_language_not_validated", None
            reasons.append(f"language '{lg}' was never validated for this model (validated: {langs_ok})")
        else:
            score = round(raw[i], 3)
            if lg not in langs_ok:
                validity = "unvalidated_language_scored_on_request"
                reasons.append(f"language '{lg}' not validated; scored only because the config asked for it")
            elif not domain_ok:
                validity = "indicative_out_of_domain"
                reasons.append("model not validated on labelled CallVerse conversations (trained on USS dialogues)")
            else:
                validity = "validated"
            if rec["input_turns"] < 4:
                reasons.append(f"input has {rec['input_turns']} turns; the model learned from multi-turn dialogues "
                               f"(median {USS_MEDIAN_TURNS})")
        rec.update(predicted_satisfaction=score, validity=validity, reasons=reasons,
                   usable_for=["kpi"] if validity == "validated" else
                   ["kpi_indicative"] if validity == "indicative_out_of_domain" else [])
        out.append(rec)
    return out


def summary(records: list[dict]) -> dict:
    import numpy as np
    from collections import Counter
    s = [r["predicted_satisfaction"] for r in records if r["predicted_satisfaction"] is not None]
    return {"n": len(records), "n_scored": len(s), "validity": dict(Counter(r["validity"] for r in records)),
            "language": dict(Counter(r["language"] for r in records)),
            "mean_indicative": round(float(np.mean(s)), 3) if s else None,
            "sd_indicative": round(float(np.std(s)), 3) if s else None,
            "note": "scores are model predictions, not client ratings; not validated on CallVerse conversations"
            if not any(r["validity"] == "validated" for r in records) else "validated model"}
