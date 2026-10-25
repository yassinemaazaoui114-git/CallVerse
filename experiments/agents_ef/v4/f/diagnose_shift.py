"""F1 — why are Agent F's satisfaction predictions nearly constant on ShopNova conversations?

    python -m v4.f.diagnose_shift --fv3 <f_v3> --corpus <m7_corpus> [--threads 2]

What it measures (all on real files; no new labels are invented):
  1. text structure   USS TEST dialogues vs ShopNova closed conversations (dev + held-out corpus): characters,
                      turns, customer turns, who speaks last, tokens (e5 + TinyBERT tokenizers), share truncated,
                      and whether the customer's words are still inside the kept (left-truncated) window.
  2. implementation   re-runs the saved checkpoints on USS TEST items and compares with the predictions stored
                      in the V3 result JSON (best seed by VAL) -> is the inference code the one that was measured?
  3. outputs          prediction distribution of each scorer (e5-L6/256, TinyBERT-EN, TF-IDF tail256) on USS TEST
                      vs ShopNova, and by corpus metadata (tone, language, outcome, planted defect). Metadata are
                      NOT satisfaction labels; they only show whether the scores move with anything at all.
  4. labels           USS TRAIN label distribution per language; prediction SD / label SD on TEST (shrinkage).
  5. probes           hand-written minimal pairs (clearly synthetic; differences between scorers' outputs only):
                      calm vs angry customer, resolved vs escalated / refused reply, EN vs FR customer,
                      + "customer closes the chat" turns (thanks / complaint) appended, + USS-format positive control.
  6. calibration      USS TEST: mean true rating per predicted-score bin, signed error per true class.
Outputs: v4/f/results/f1_diagnosis.json, v4/f/results/f1_predictions.json (cache), figures in v4/f/figures/.
"""

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]                                       # experiments/agents_ef
sys.path.insert(0, str(ROOT))

SCORERS = {  # name -> (kind, checkpoint subfolder, V3 result json, languages it was trained on)
    "e5_L6_256": ("f", "e5small_trim_ft_L6_frac0.5_len256_s1", "e5small_trim_ft_L6_frac0.5_len256.json", ["en", "zh"]),
    "tinybert_en": ("f", "tinybert_ft_en_frac0.5_len128_s1", "tinybert_ft_en_frac0.5_len128.json", ["en"]),
    "tfidf_tail256": ("tfidf", "tfidf_ridge_tail256", "tfidf_ridge_tail256tok.json", ["en", "zh"]),
}

# ---------------- minimal-pair probes (hand-written, synthetic; NOT labels) ----------------
# Replies are copied from real template replies of the corpus (same wording the prototype produces).
R_REFUND_OK = ("Hello, good news about your order 4512. Its current status is refunded; it is 8 days late; the amount "
               "is 59.90 TND. Your refund of 59.90 TND is approved. Your order 4512 is now cancelled.")
R_ESCALATE = "I'm sorry for the trouble. Your case needs an extra check, so it has been passed on for review."
R_REFUSED = ("I'm sorry for the trouble. We cannot approve a refund of 378.00 TND for order 4515. Our finance team "
             "reviewed it and did not approve it.")
R_STATUS = ("Hello, here is the latest information about your order 5030. Its current status is out for delivery; "
            "it is 2 days late; the promised delivery date was 2026-10-07; the carrier is Aramex. If you like, we can "
            "send you a message when it is out for delivery. Your order 5030 is out for delivery.")
C_CALM = {"refund": "Hello, my order 4512 is very late. Could I get a refund, please?",
          "status": "Hi, could you tell me where my order 5030 is, please?"}
C_ANGRY = {"refund": "Order 4512 STILL has not arrived. This is a joke. Refund me NOW, I am done with ShopNova.",
           "status": "Where is my order 5030?! This is the third time I ask. Terrible service."}
C_FR = {"refund": "Bonjour, ma commande 4512 est très en retard. Puis-je être remboursé, s'il vous plaît ?",
        "status": "Bonjour, pouvez-vous me dire où en est ma commande 5030, s'il vous plaît ?"}
CLOSE_POS = "Customer: Great, thank you so much, that solves it!"
CLOSE_NEG = "Customer: This is useless. You did not help me at all."
USS_POS = ("Customer: I need a hotel in Paris for two nights.\nAgent: Hotel Lumiere has a room for 2 nights at 90 euros.\n"
           "Customer: Book it please.\nAgent: Done, your booking is confirmed.\nCustomer: Perfect, thank you so much!")
USS_NEG = ("Customer: I need a hotel in Paris for two nights.\nAgent: Sorry, I could not find anything.\n"
           "Customer: Can you check again? Any hotel is fine.\nAgent: Sorry, I could not find anything.\n"
           "Customer: This is useless, you did not help at all.")


def probe_set():
    """List of (probe group, variant name, text). Each group compares variants that differ in ONE thing."""
    P = []
    for intent, reply in (("refund", R_REFUND_OK), ("status", R_STATUS)):
        for name, cust in (("calm", C_CALM), ("angry", C_ANGRY), ("fr", C_FR)):
            P.append((f"tone_lang/{intent}", name, f"Customer: {cust[intent]}\nAgent: {reply}"))
    for name, reply in (("resolved", R_REFUND_OK), ("escalated", R_ESCALATE), ("refused", R_REFUSED)):
        for tone, cust in (("calm", C_CALM), ("angry", C_ANGRY)):
            P.append((f"outcome/{tone}", name, f"Customer: {cust['refund']}\nAgent: {reply}"))
    base = f"Customer: {C_CALM['refund']}\nAgent: {R_REFUND_OK}"
    for name, extra in (("no_close", ""), ("close_thanks", "\n" + CLOSE_POS), ("close_complaint", "\n" + CLOSE_NEG)):
        P.append(("closing_turn/refund_ok", name, base + extra))
    base = f"Customer: {C_CALM['refund']}\nAgent: {R_ESCALATE}"
    for name, extra in (("no_close", ""), ("close_thanks", "\n" + CLOSE_POS), ("close_complaint", "\n" + CLOSE_NEG)):
        P.append(("closing_turn/escalated", name, base + extra))
    P += [("uss_format_control", "positive", USS_POS), ("uss_format_control", "negative", USS_NEG)]
    return P


# ---------------- helpers ----------------
def load_rows(folder, split):
    return [json.loads(line) for line in open(Path(folder) / f"{split}.jsonl", encoding="utf-8")]


def load_scorer(name, fv3):
    kind, sub, _, _ = SCORERS[name]
    path = Path(fv3) / "ckpt" / sub
    if kind == "tfidf":
        from v4.f.tfidf_predictor import TfidfSatisfactionPredictor
        return TfidfSatisfactionPredictor.load(path)
    from v3.f.f_predictor import SatisfactionPredictor
    return SatisfactionPredictor.load(path)


def score(scorer, texts, langs=None):
    if langs is not None and hasattr(scorer, "word"):
        return [float(x) for x in scorer.scores(texts, langs)]
    return [float(x) for x in scorer.scores(texts)]


def turns(text):
    lines = [l for l in text.split("\n") if l.strip()]
    cust = [l for l in lines if l.startswith(("Customer:", "客户:"))]
    return lines, cust


def describe(v):
    v = np.asarray(v, float)
    return {"n": int(len(v)), "mean": round(float(v.mean()), 4), "sd": round(float(v.std()), 4),
            "min": round(float(v.min()), 4), "p10": round(float(np.percentile(v, 10)), 4),
            "p50": round(float(np.percentile(v, 50)), 4), "p90": round(float(np.percentile(v, 90)), 4),
            "max": round(float(v.max()), 4)}


def structure(texts, tok_e5, tok_tb):
    """Structure statistics of a list of dialogue texts, incl. what the left-truncated window keeps."""
    out = defaultdict(list)
    for t in texts:
        lines, cust = turns(t)
        out["chars"].append(len(t))
        out["turns"].append(len(lines))
        out["customer_turns"].append(len(cust))
        out["last_speaker_customer"].append(float(bool(lines) and lines[-1].startswith(("Customer:", "客户:"))))
        ids = tok_e5("query: " + t)["input_ids"]
        out["e5_tokens"].append(len(ids))
        out["e5_truncated_256"].append(float(len(ids) > 256))
        out["tinybert_tokens"].append(len(tok_tb(t)["input_ids"]))
        out["tinybert_truncated_128"].append(float(len(tok_tb(t)["input_ids"]) > 128))
        # Is the customer still visible after LEFT truncation to 256 e5 tokens? Count customer characters inside
        # the kept tail (approximation: map the kept token share onto characters).
        keep_frac = min(1.0, 256 / max(1, len(ids)))
        kept = t[-int(len(t) * keep_frac):] if keep_frac < 1 else t
        k_lines, k_cust = turns(kept)
        cust_chars = sum(len(l) for l in k_cust)
        out["customer_char_share_in_window"].append(cust_chars / max(1, len(kept)))
        out["customer_turns_in_window"].append(len(k_cust))
    return {k: describe(v) if k not in ("last_speaker_customer", "e5_truncated_256", "tinybert_truncated_128")
            else round(float(np.mean(v)), 4) for k, v in out.items()}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--fv3", required=True)
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--n-repro", type=int, default=60, help="USS TEST items re-scored for the implementation check")
    a = ap.parse_args(argv)
    import torch
    torch.set_num_threads(a.threads)
    from scipy.stats import spearmanr
    from transformers import AutoTokenizer
    from v3.m7.conversations import dialogue_text, load_conversations

    res_dir = HERE / "results"
    cache_p = res_dir / "f1_predictions.json"
    cache = json.loads(cache_p.read_text()) if cache_p.exists() else {}
    data = Path(a.fv3) / "data_uss"
    tr, te = load_rows(data, "train"), load_rows(data, "test")
    te_texts, te_langs = [r["text"] for r in te], [r["lang"] for r in te]
    y_te = np.array([r["rating"] for r in te])

    # ShopNova corpus: dev + held-out test (F1 only DESCRIBES predictions; nothing is tuned on either)
    sn = []
    for split in ("dev", "test"):
        gt = {g["conversation_id"]: g for g in
              json.loads((Path(a.corpus) / split / "ground_truth.json").read_text())["conversations"]}
        for c in load_conversations(Path(a.corpus) / split / "traces"):
            g = gt.get(c["conversation_id"], {})
            sn.append({"split": split, "id": c["conversation_id"], "text": dialogue_text(c),
                       "lang": g.get("lang"), "tone": g.get("tone"), "intent": g.get("intent"),
                       "outcome": (c.get("decision") or {}).get("outcome"), "defect": g.get("planted_defect")})
    sn_texts = [s["text"] for s in sn]
    probes = probe_set()
    probe_texts = [p[2] for p in probes]

    rep = {"created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "n_uss_test": len(te),
           "n_shopnova": len(sn), "shopnova_by_split": {s: sum(x["split"] == s for x in sn) for s in ("dev", "test")}}

    # 1. structure
    tok_e5 = AutoTokenizer.from_pretrained("intfloat/multilingual-e5-small")
    tok_tb = AutoTokenizer.from_pretrained("huawei-noah/TinyBERT_General_4L_312D")
    rep["structure"] = {"uss_test_all": structure(te_texts, tok_e5, tok_tb),
                        "uss_test_en": structure([t for t, l in zip(te_texts, te_langs) if l == "en"], tok_e5, tok_tb),
                        "shopnova": structure(sn_texts, tok_e5, tok_tb)}
    # unknown-token rate for TinyBERT (EN vocabulary) on French ShopNova text
    unk = tok_tb.unk_token_id
    fr = [s["text"] for s in sn if s["lang"] == "fr"]
    rep["structure"]["tinybert_unk_rate_fr_shopnova"] = round(float(np.mean(
        [np.mean(np.array(tok_tb(t)["input_ids"]) == unk) for t in fr])), 5) if fr else None

    # 4. labels
    lab = {}
    for lg in ("en", "zh"):
        v = np.array([r["rating"] for r in tr if r["lang"] == lg])
        lab[lg] = {**describe(v), "share_in_[2.5,3.5)": round(float(((v >= 2.5) & (v < 3.5)).mean()), 4),
                   "share_below_2.5": round(float((v < 2.5).mean()), 4)}
    rep["labels_uss_train"] = lab

    # 2/3/5/6 per scorer
    rep["scorers"] = {}
    for name, (kind, sub, resname, langs_ok) in SCORERS.items():
        t0 = time.perf_counter()
        s = load_scorer(name, a.fv3)
        res = json.loads((ROOT / "v3/f/results/uss" / resname).read_text())
        run = next(r for r in res["runs"] if r.get("seed", 0) == res.get("best_seed_by_val", 0))
        id2pred = dict(zip(res["test_ids"], run["test_pred"]))
        id2row = {r["id"]: r for r in te}
        entry = {"checkpoint": sub, "result_file": f"v3/f/results/uss/{resname}", "seed": run.get("seed", 0),
                 "languages_trained": langs_ok}
        # 2. implementation check on the first n_repro TEST ids of that run
        ids = res["test_ids"][:a.n_repro]
        rows = [id2row[i] for i in ids]
        mine = np.array(score(s, [r["text"] for r in rows], [r["lang"] for r in rows]))
        stored = np.clip(np.array([id2pred[i] for i in ids], float), 1, 5)
        entry["reproduction"] = {"n": len(ids), "max_abs_diff": round(float(np.abs(mine - stored).max()), 6),
                                 "mean_abs_diff": round(float(np.abs(mine - stored).mean()), 6)}
        # 3. distributions (cached, the neural scorers are slow on a shared CPU)
        key = f"{name}"
        if key not in cache:
            uss_ids = res["test_ids"]
            uss_rows = [id2row[i] for i in uss_ids]
            cache[key] = {"uss_ids": uss_ids,
                          "uss": score(s, [r["text"] for r in uss_rows], [r["lang"] for r in uss_rows]),
                          "shopnova": score(s, sn_texts), "probes": score(s, probe_texts)}
            cache_p.write_text(json.dumps(cache))
        c = cache[key]
        uy = np.array([id2row[i]["rating"] for i in c["uss_ids"]])
        up = np.array(c["uss"])
        ulang = [id2row[i]["lang"] for i in c["uss_ids"]]
        entry["uss_test_pred"] = describe(up)
        entry["uss_test_pred_en"] = describe(up[[l == "en" for l in ulang]])
        entry["uss_test_label_sd"] = round(float(uy.std()), 4)
        entry["uss_test_pred_sd_over_label_sd"] = round(float(up.std() / uy.std()), 4)
        entry["uss_test_mae_recomputed"] = round(float(np.abs(up - uy).mean()), 4)
        entry["uss_test_spearman_recomputed"] = round(float(spearmanr(uy, up).statistic), 4)
        sp = np.array(c["shopnova"])
        entry["shopnova_pred"] = describe(sp)
        entry["shopnova_sd_over_uss_sd"] = round(float(sp.std() / up.std()), 4)
        by = {}
        for field in ("tone", "lang", "intent", "outcome", "split"):
            g = defaultdict(list)
            for x, v in zip(sn, sp):
                g[str(x[field])].append(v)
            by[field] = {k: {"n": len(v), "mean": round(float(np.mean(v)), 4), "sd": round(float(np.std(v)), 4)}
                         for k, v in sorted(g.items())}
        g = defaultdict(list)
        for x, v in zip(sn, sp):
            g["clean" if x["defect"] is None else "planted_defect"].append(v)
        by["defect"] = {k: {"n": len(v), "mean": round(float(np.mean(v)), 4)} for k, v in g.items()}
        entry["shopnova_by_metadata"] = by
        # 5. probes: per group, every variant minus the first variant
        pr = defaultdict(dict)
        for (grp, var, _), v in zip(probes, c["probes"]):
            pr[grp][var] = round(v, 4)
        entry["probes"] = {g: {"scores": d, "delta_vs_" + next(iter(d)): {k: round(v - next(iter(d.values())), 4)
                                                                          for k, v in d.items()}}
                           for g, d in pr.items()}
        # 6. calibration on USS TEST
        bins = np.quantile(up, np.linspace(0, 1, 6))
        idx = np.clip(np.digitize(up, bins[1:-1]), 0, 4)
        entry["calibration_uss_test_quintiles"] = [
            {"pred_mean": round(float(up[idx == b].mean()), 4), "true_mean": round(float(uy[idx == b].mean()), 4),
             "n": int((idx == b).sum())} for b in range(5) if (idx == b).any()]
        yi = np.clip(np.floor(uy + 0.5), 1, 5)
        entry["signed_error_by_true_class"] = {int(k): round(float((up[yi == k] - uy[yi == k]).mean()), 4)
                                               for k in range(1, 6) if (yi == k).any()}
        entry["seconds"] = round(time.perf_counter() - t0, 1)
        rep["scorers"][name] = entry
        print(name, "repro", entry["reproduction"], "uss sd", entry["uss_test_pred"]["sd"], "shopnova sd",
              entry["shopnova_pred"]["sd"], flush=True)
        del s

    (res_dir / "f1_diagnosis.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False))
    figures(rep, cache, te, sn)
    print("wrote", res_dir / "f1_diagnosis.json")


def figures(rep, cache, te, sn):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig_dir = HERE / "figures"
    names = list(rep["scorers"])
    # (a) prediction histograms USS TEST vs ShopNova
    fig, axes = plt.subplots(1, len(names), figsize=(4.2 * len(names), 3.3), sharey=False)
    for ax, n in zip(axes, names):
        c = cache[n]
        ax.hist(c["uss"], bins=np.linspace(1, 5, 41), alpha=0.6, density=True, label="USS TEST (labelled)")
        ax.hist(c["shopnova"], bins=np.linspace(1, 5, 41), alpha=0.6, density=True, label="ShopNova corpus (no labels)")
        ax.set_title(f"{n}\nUSS SD {np.std(c['uss']):.2f} | ShopNova SD {np.std(c['shopnova']):.2f}", fontsize=9)
        ax.set_xlabel("predicted satisfaction (1-5)")
    axes[0].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(fig_dir / "f1_pred_hist_uss_vs_shopnova.png", dpi=130)
    plt.close(fig)
    # (b) structure: tokens and turns
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained("intfloat/multilingual-e5-small")
    lu = [len(tok("query: " + r["text"])["input_ids"]) for r in te]
    ls = [len(tok("query: " + s["text"])["input_ids"]) for s in sn]
    fig, ax = plt.subplots(1, 2, figsize=(9, 3.3))
    ax[0].hist(np.log10(lu), bins=40, alpha=0.6, label="USS TEST", density=True)
    ax[0].hist(np.log10(ls), bins=20, alpha=0.6, label="ShopNova", density=True)
    ax[0].axvline(np.log10(256), color="k", ls="--", lw=1)
    ax[0].set_xlabel("log10(e5 tokens); dashed = 256-token window")
    ax[0].legend(fontsize=8)
    tu = [len([l for l in r["text"].split("\n") if l.strip()]) for r in te]
    ts = [len([l for l in s["text"].split("\n") if l.strip()]) for s in sn]
    ax[1].hist(tu, bins=np.arange(0, 60, 2), alpha=0.6, label="USS TEST", density=True)
    ax[1].hist(ts, bins=np.arange(0, 60, 2), alpha=0.6, label="ShopNova", density=True)
    ax[1].set_xlabel("turns per conversation")
    fig.tight_layout()
    fig.savefig(fig_dir / "f1_structure_tokens_turns.png", dpi=130)
    plt.close(fig)
    # (c) probes
    groups = list(rep["scorers"][names[0]]["probes"])
    fig, axes = plt.subplots(1, len(groups), figsize=(3.1 * len(groups), 3.4), sharey=True)
    for ax, g in zip(axes, groups):
        variants = list(rep["scorers"][names[0]]["probes"][g]["scores"])
        x = np.arange(len(variants))
        for k, n in enumerate(names):
            ax.bar(x + (k - 1) * 0.27, [rep["scorers"][n]["probes"][g]["scores"][v] for v in variants], 0.27, label=n)
        ax.set_xticks(x)
        ax.set_xticklabels(variants, rotation=45, ha="right", fontsize=7)
        ax.set_title(g, fontsize=8)
        ax.set_ylim(1, 5)
    axes[0].legend(fontsize=6)
    axes[0].set_ylabel("predicted score")
    fig.tight_layout()
    fig.savefig(fig_dir / "f1_probes.png", dpi=130)
    plt.close(fig)
    # (d) calibration
    fig, ax = plt.subplots(figsize=(4, 3.6))
    for n in names:
        cal = rep["scorers"][n]["calibration_uss_test_quintiles"]
        ax.plot([c["pred_mean"] for c in cal], [c["true_mean"] for c in cal], "o-", label=n)
    ax.plot([2, 4], [2, 4], "k--", lw=1)
    ax.set_xlabel("mean predicted (USS TEST quintile)")
    ax.set_ylabel("mean true label")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(fig_dir / "f1_calibration_uss_test.png", dpi=130)
    plt.close(fig)


if __name__ == "__main__":
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    main()
