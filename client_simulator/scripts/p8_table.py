"""TASK3 tables from result files -> results/p8_tables.md. python p8_table.py WRITER_MODEL WRITER_PV"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import RESULTS, load_json  # noqa: E402

SRC = ["csat", "olist", "tripadvisor", "uss"]
NAMES = {"csat": "Flipkart CSAT (customer)", "olist": "Olist (customer, PT)", "tripadvisor": "TripAdvisor (customer)",
         "uss": "USS travel dialogues (annotators)"}


def f(x, d=2):
    return "n/a" if x is None else f"{x:.{d}f}"


def fc(x, c, d=2):
    return f"{f(x, d)} [{f(c[0], d)}, {f(c[1], d)}]"


def main(writer, wpv):
    fs = load_json(RESULTS / "p8_fairspeed.json")
    rl = load_json(RESULTS / "p8_writers_realism.json")
    pr = load_json(RESULTS / "p8_writers_probe.json")
    t1n = load_json(RESULTS / "p8_test1_scores.json")["per_model"] if (RESULTS / "p8_test1_scores.json").exists() else {}
    t1o = load_json(RESULTS / "p3_test1_scores.json")["per_model"]
    sc = load_json(RESULTS / "p8_scorer_final.json")
    kv = "KV q8_0 + flash attention, num_ctx 1024"
    out = []
    # ---------------- final comparison
    ph = fs[f"phi4-mini:3.8b | {kv}"]
    nw = fs.get(f"{writer} | main server restarted (KV q8_0 + flash attention), 127.0.0.1, num_ctx 1024") or fs[f"{writer} | {kv}"]
    phd, nwd = fs["phi4-mini:3.8b | default server, num_ctx 4096"], fs.get(f"{writer} | default server, num_ctx 4096")
    p_c, m_c = sc["scorers"]["phi4mini_llm_baseline"]["csat"], sc["scorers"]["minilm_finetuned_int8_quantile"]["csat"]
    r_ph = rl["phi4-mini:3.8b | rp1-ex5"]["distance_mean"]
    r_ph0 = rl["phi4-mini:3.8b | rp1-noex"]["distance_mean"]
    r_nw = rl[f"{writer} | {wpv}"]["distance_mean"]
    t_nw = t1n.get(writer, {})
    out += ["## Final comparison (writer on the same 30 role cards; scorer on the same 1,000 real Flipkart CSAT test rows)", "",
            "| Setup | GPU memory alone | GPU memory with qwen2.5:3b | Seconds per turn | Realism distance (lower = better) | Realism (0-6) | Stays in role (0-6) | Score MAE [95% CI] | Score QWK [95% CI] | Distance to real score distribution |",
            "|---|---|---|---|---|---|---|---|---|---|",
            f"| **Before:** phi4-mini:3.8b writer + phi4-mini LLM scoring (main calibration) | {ph['vram_alone_mib']} MiB | {ph['nvidia_smi_with_qwen_mib']} MiB | "
            f"{ph['sec_per_message']} s | {f(r_ph0, 3)} (no examples) / {f(r_ph, 3)} (5 examples) | "
            f"{t1o['phi4-mini:3.8b']['realism']} | {t1o['phi4-mini:3.8b']['role']} | {fc(p_c['mae'], p_c['mae_ci'])} | {fc(p_c['qwk'], p_c['qwk_ci'])} | {f(p_c['wasserstein'])} |",
            f"| **After:** {writer} writer + MiniLM int8 CPU scorer (quantile setting) | {nw['vram_alone_mib']} MiB (+0 GPU for the scorer) | {nw['nvidia_smi_with_qwen_mib']} MiB | "
            f"{nw['sec_per_message']} s + {sc['minilm_info']['ms_per_score']} ms per score (CPU) | "
            f"{f(r_nw, 3)} | {t_nw.get('realism', 'n/a')} | {t_nw.get('role', 'n/a')} | {fc(m_c['mae'], m_c['mae_ci'])} | {fc(m_c['qwk'], m_c['qwk_ci'])} | {f(m_c['wasserstein'])} |",
            "", f"Seconds per turn and memory: same prompt, Ollama with {kv}, requests to 127.0.0.1 (with 'localhost' Windows adds about 2 s "
                "per request; all earlier phases include that overhead). Memory with qwen2.5:3b = nvidia-smi increase with both models loaded.", ""]
    # ---------------- writers
    out += ["## Writer candidates (Test 2: 30 role cards x 3 turns; Test 1 judged blind by Claude Code)", "",
            "| Writer | Licence | Prompt | Realism distance | Breaks role | Empty replies | Realism (0-6) | Role (0-6) | VRAM alone | s/message (default server) |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    lic = {"gemma3:1b": "Gemma Terms of Use", "gemma3:270m": "Gemma Terms of Use", "llama3.2:1b": "Llama 3.2 Community",
           "smollm2:1.7b": "Apache 2.0", "granite4:350m": "Apache 2.0", "callverse-sim-writer": "Gemma Terms of Use (fine-tune of gemma-3-1b-it)",
           "phi4-mini:3.8b": "MIT"}
    rows = []
    for k, v in rl.items():
        m, pv = k.split(" | ")
        if m not in lic or pv not in ("rp1-ex5", "rp1-noex", "rp1-ft"):
            continue
        p = pr.get(m, {})
        t = t1n.get(m) or (t1o.get(m) if pv == "rp1-noex" else {}) or {}
        rows.append((v["distance_mean"], f"| {m} | {lic[m]} | {pv} | {f(v['distance_mean'], 3)} | {f(100 * v['breaks_role_rate'], 1)}% | "
                                         f"{f(100 * v['empty_rate'], 1)}% | {t.get('realism', 'n/a')} | {t.get('role', 'n/a')} | "
                                         f"{p.get('vram_mib', 'n/a')} MiB | {p.get('sec_per_message', 'n/a')} |"))
    out += [r for _, r in sorted(rows)] + [""]
    # ---------------- scorers
    out += ["## Scorers on held-out REAL test sets (95% bootstrap CI)", "",
            "| Test set (n, who scored) | Scorer | MAE | QWK | +-1 acc | Distance to real distribution |", "|---|---|---|---|---|---|"]
    for s in SRC:
        for k, lab in (("phi4mini_llm_baseline", "phi4-mini LLM (before)"), ("cpu_classic", "classic CPU (TF-IDF / GBM)"),
                       ("minilm_finetuned_int8", "MiniLM fine-tuned, int8, isotonic (plain option)"),
                       ("minilm_finetuned_int8_quantile", "MiniLM fine-tuned, int8, quantile (**default**)")):
            x = sc["scorers"].get(k, {}).get(s)
            if not x:
                continue
            out.append(f"| {NAMES[s]} (n={x['n']}) | {lab} | {fc(x['mae'], x['mae_ci'])} | {fc(x['qwk'], x['qwk_ci'])} | "
                       f"{f(x['within1_acc'])} | {f(x['wasserstein'])} |")
    out += ["", f"Classic CPU choice per source (dev): " + "; ".join(f"{s}: {sc['scorers']['cpu_classic'][s]['chosen_on_dev']}" for s in SRC),
            f"MiniLM: {sc['minilm_info']['size_mb_int8']} MB int8 ({sc['minilm_info']['size_mb_fp32']} MB fp32), {sc['minilm_info']['ms_per_score']} ms per score on CPU; "
            f"classic: TF-IDF+LR {sc['cpu_classic_info']['ms_per_score']['tfidf_lr']} ms, GBM {sc['cpu_classic_info']['ms_per_score']['gbm_feats_svd']} ms per score.", ""]
    for s, lab in (("csat", "waiting time"), ("olist", "delivery lateness")):
        out += [f"**Mean score per {lab} bucket, {NAMES[s]} test (real vs scorer, 95% CI)**", "",
                "| Bucket | n | real | phi4-mini (before) | MiniLM quantile (after) |", "|---|---|---|---|---|"]
        a = sc["scorers"]["minilm_finetuned_int8_quantile"][s]["by_bucket"]
        b = sc["scorers"]["phi4mini_llm_baseline"][s].get("by_bucket", {})
        for k, v in a.items():
            pb = b.get(k)
            out.append(f"| {k} | {v['n']} | {fc(v['real_mean'], v['real_mean_ci'])} | "
                       f"{fc(pb['sim_mean'], pb['sim_mean_ci']) if pb else 'n/a'} | {fc(v['sim_mean'], v['sim_mean_ci'])} |")
        out += [f"| size-weighted gap | | | {fc(sc['scorers']['phi4mini_llm_baseline'][s]['bucket_gap'], sc['scorers']['phi4mini_llm_baseline'][s]['bucket_gap_ci'])} | "
                f"{fc(sc['scorers']['minilm_finetuned_int8_quantile'][s]['bucket_gap'], sc['scorers']['minilm_finetuned_int8_quantile'][s]['bucket_gap_ci'])} |", ""]
    (RESULTS / "p8_tables.md").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out[:6]))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
