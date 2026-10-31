"""TASK3 evaluation. python p8_final.py scorer | writers | sheet MODEL... | table
scorer : CPU scorer (p8_scorer_cpu), fine-tuned MiniLM ONNX (Kaggle job B) and the phi4-mini baseline on the same REAL test rows
writers: realism distance + breaks-role for every tested writer (Test 2), from the LLM cache
sheet  : blind Test 1 sheet for the small writers (judged by Claude Code)"""
import json
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import CACHE, PROC, RESULTS, ROOT, SEED, load_json, read_jsonl, save_json  # noqa: E402
from llm import parse_score  # noqa: E402
from p3_make_cards import all_cards  # noqa: E402
from p7_large import qwk_fast, with_ci  # noqa: E402
from realism import profile, realism_distance  # noqa: E402
from simulator.prompts import breaks_role  # noqa: E402

L = PROC / "lean"
SRC = ["csat", "olist", "tripadvisor", "uss"]
BUCKETS = {"csat": ["0-5 min", "5-30 min", "30 min-2 h", "2-8 h", "8 h+"],
           "olist": ["on time or early", "1-3 days late", "4-7 days late", "8+ days late", "never delivered"]}
ONNX_DIR = ROOT / "models" / "scorer"   # int8 ONNX + tokenizer.json (Kaggle job B output, copied)


class OnnxScorer:
    def __init__(self, path=ONNX_DIR, model="scorer_int8.onnx", maxlen=256):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        self.tok = Tokenizer.from_file(str(Path(path) / "tokenizer.json"))
        self.tok.enable_truncation(maxlen)
        self.tok.enable_padding()
        so = ort.SessionOptions()
        so.intra_op_num_threads = 4
        self.s = ort.InferenceSession(str(Path(path) / model), so, providers=["CPUExecutionProvider"])

    def __call__(self, texts, bs=32):
        out = []
        for i in range(0, len(texts), bs):
            e = self.tok.encode_batch(list(texts[i:i + bs]))
            ids = np.array([x.ids for x in e], dtype=np.int64)
            att = np.array([x.attention_mask for x in e], dtype=np.int64)
            out.append(self.s.run(None, {"input_ids": ids, "attention_mask": att})[0].reshape(-1))
        return np.clip(np.concatenate(out) * 2 + 3, 1, 5)


def phi_baseline(te):
    """phi4-mini + main calibration (existing results) on the same rows where it exists."""
    p3 = load_json(RESULTS / "p3_test3_scores.json")["phi4-mini:3.8b"]
    out = {}
    for name, src, cache, pv in (("csat", "csat", "test3_csat", "s2"), ("conv", "uss", "test3_conv", "s2")):
        c = {r["item"]: r for r in read_jsonl(CACHE / f"{cache}.jsonl") if r["model"] == "phi4-mini:3.8b" and r["pv"] == pv}
        t = te[te.source == src]
        ch = p3[name]["chosen_on_dev"]
        mp = p3[name]["calibration_maps_fit_on_cal"][ch.split("-")[1]] if ch.startswith("v3") else None
        raw = [parse_score(c[i]["text"])[0] if i in c else None for i in t.id]
        keep = [r is not None for r in raw]
        fill = 3 if name == "conv" else 5
        pred = [mp[str(r)] if mp else r for r in [x if x is not None else fill for x in raw]]
        out[src] = {"pred": np.array(pred, float), "covered": int(sum(i in c for i in t.id)), "calibration": f"Phase 3 main ({ch})"}
    fb = load_json(ROOT / "simulator" / "calibration_fallback.json")["models"]["phi4-mini:3.8b"]["map"]
    c = {r["item"]: r for r in read_jsonl(CACHE / "p6_fallback.jsonl") if r["model"] == "phi4-mini:3.8b"}
    t = te[te.source == "olist"]
    out["olist"] = {"pred": np.array([fb[str(parse_score(c[i]["text"])[0] or 5)] if i in c else np.nan for i in t.id], float),
                    "covered": int(sum(i in c for i in t.id)), "calibration": "fallback map (Olist), the only phi4-mini setup for Olist"}
    return out


def scorer():
    te = pd.DataFrame(read_jsonl(L / "scorer_test.jsonl"))
    dv = pd.DataFrame(read_jsonl(L / "scorer_dev.jsonl"))
    res = {"test_sizes": te.source.value_counts().to_dict(), "scorers": {}}
    cpu = load_json(RESULTS / "p8_scorer_cpu.json")
    # 1. CPU (choice per source on dev, from p8_scorer_cpu)
    for s in SRC:
        p = pd.read_csv(RESULTS / f"p8_scorer_cpu_test_{s}.csv")
        t = te[te.source == s].set_index("id").loc[p.id]
        res["scorers"].setdefault("cpu_classic", {})[s] = with_ci(p.label.values, p.pred.values, t.bucket.values if s in BUCKETS else None, BUCKETS.get(s))
        res["scorers"]["cpu_classic"][s]["chosen_on_dev"] = cpu["per_source"][s]["chosen_on_dev"]
    kinds = sorted({v["chosen_on_dev"].split(" | ")[0] for v in cpu["per_source"].values()})
    res["cpu_classic_info"] = {"ms_per_score": cpu["ms_per_score"], "kinds_used": kinds,
                               "size_mb_models_used": {k: v["mb"] for k, v in cpu["fit_log"].items()}}
    # 2. fine-tuned MiniLM (Kaggle job B) on CPU, int8 ONNX; isotonic fit on dev half A, chosen per source on dev half B
    if (ONNX_DIR / "scorer_int8.onnx").exists():
        sc = OnnxScorer()
        dsub = pd.concat([g.sample(min(1500, len(g)), random_state=SEED) for _, g in dv.groupby("source")])
        dsub["pred"] = sc(dsub.text.values)
        dsub["half"] = np.random.RandomState(SEED).rand(len(dsub)) < 0.5
        tp = sc(te.text.values)
        te["onnx"] = tp
        info = {}
        for s in SRC:
            A, B = dsub[(dsub.source == s) & dsub.half], dsub[(dsub.source == s) & ~dsub.half]
            iso = IsotonicRegression(y_min=1, y_max=5, out_of_bounds="clip").fit(A.pred, A.label)
            qx = np.sort(A.pred.values)
            qy = np.sort(A.label.values.astype(float))
            grid = np.linspace(0, 1, 101)
            qmap = (np.quantile(qx, grid), np.quantile(qy, grid))   # distribution matching: pred quantile -> real quantile
            fns = {"none": lambda v: v, "isotonic": iso.predict, "quantile": lambda v: np.interp(v, *qmap)}
            dq = {k: qwk_fast(B.label.values, np.clip(np.floor(fn(B.pred.values) + .5), 1, 5).astype(int)) for k, fn in fns.items()}
            best = max(dq, key=dq.get)
            t = te[te.source == s]
            pred = fns[best](t.onnx.values)
            res["scorers"].setdefault("minilm_finetuned_int8", {})[s] = with_ci(t.label.values, pred, t.bucket.values if s in BUCKETS else None, BUCKETS.get(s))
            res["scorers"]["minilm_finetuned_int8"][s]["chosen_on_dev"] = f"{best} (dev B QWK " + ", ".join(f"{k} {v:.3f}" for k, v in dq.items()) + ")"
            res["scorers"].setdefault("minilm_finetuned_int8_quantile", {})[s] = with_ci(
                t.label.values, fns["quantile"](t.onnx.values), t.bucket.values if s in BUCKETS else None, BUCKETS.get(s))
            for k, fn in fns.items():  # transparency: every calibration on test
                res.setdefault("minilm_all_calibrations_test", {}).setdefault(s, {})[k] = {
                    x: with_ci(t.label.values, fn(t.onnx.values))[x] for x in ("mae", "qwk", "wasserstein")}
            info[s] = {"method": best, "isotonic": best == "isotonic",
                       "isotonic_map": [iso.X_thresholds_.tolist(), iso.y_thresholds_.tolist()],
                       "quantile_map": [qmap[0].tolist(), qmap[1].tolist()],
                       "x": (iso.X_thresholds_.tolist() if best == "isotonic" else qmap[0].tolist() if best == "quantile" else None),
                       "y": (iso.y_thresholds_.tolist() if best == "isotonic" else qmap[1].tolist() if best == "quantile" else None)}
        pickle.dump(info, open(RESULTS / "p8_minilm_isotonic.pkl", "wb"))
        save_json(info, RESULTS / "p8_minilm_isotonic.json")
        one = te.sample(200, random_state=SEED).text.values
        s0 = time.time()
        for x in one:
            sc([x])
        res["minilm_info"] = {"ms_per_score": round(1000 * (time.time() - s0) / len(one), 2),
                              "size_mb_int8": round((ONNX_DIR / "scorer_int8.onnx").stat().st_size / 2**20, 1),
                              "size_mb_fp32": round((ONNX_DIR / "scorer.onnx").stat().st_size / 2**20, 1) if (ONNX_DIR / "scorer.onnx").exists()
                              else 127.5}  # fp32 file deleted after the first evaluation (127.5 MB measured then)
    else:
        res["minilm_info"] = "Kaggle job B output not available"
    # 3. phi4-mini baseline
    ph = phi_baseline(te)
    for s, v in ph.items():
        t = te[te.source == s]
        ok = ~np.isnan(v["pred"])
        res["scorers"].setdefault("phi4mini_llm_baseline", {})[s] = {
            **with_ci(t.label.values[ok], v["pred"][ok], t.bucket.values[ok] if s in BUCKETS else None, BUCKETS.get(s)),
            "covered_rows": v["covered"], "calibration": v["calibration"]}
    res["phi4mini_llm_baseline"] = {"note": "no phi4-mini run exists for TripAdvisor"}
    save_json(res, RESULTS / "p8_scorer_final.json")
    for k, v in res["scorers"].items():
        print(k, {s: (round(x["qwk"], 3), round(x["mae"], 3)) for s, x in v.items()})


def writers():
    p3 = load_json(RESULTS / "p3_test2_realism.json")
    real_first, real_later = p3["real_first"], p3["real_later"]
    comp = {c["id"]: c["company"] for c in all_cards()}
    cache = pd.DataFrame(read_jsonl(CACHE / "test2.jsonl"))
    out = {}
    for (m, pv), d in cache.groupby(["model", "pv"]):
        d = d.assign(card=d["item"].str.split(":").str[0], turn=d["item"].str.split(":").str[1])
        f, l = d[d.turn == "t0"], d[d.turn != "t0"]
        pf = profile(f.text.str.strip().tolist(), f.card.map(comp).tolist())
        pl = profile(l.text.str.strip().tolist(), l.card.map(comp).tolist())
        df_, _ = realism_distance(pf, real_first)
        dl, _ = realism_distance(pl, real_later)
        out[f"{m} | {pv}"] = {"distance_mean": (df_ + dl) / 2, "distance_first": df_, "distance_later": dl,
                              "breaks_role_rate": float(d.text.map(breaks_role).mean()), "n": int(len(d)),
                              "empty_rate": float((d.text.str.strip() == "").mean()), "words_median_first": pf["words_median"],
                              "spelling_first": pf["share_spelling_error"]}
    save_json(out, RESULTS / "p8_writers_realism.json")
    for k, v in sorted(out.items(), key=lambda x: x[1]["distance_mean"]):
        print(f"{k}: {v['distance_mean']:.3f} br {v['breaks_role_rate']:.3f} empty {v['empty_rate']:.2f}")


if __name__ == "__main__":
    {"scorer": scorer, "writers": writers}[sys.argv[1]]()
