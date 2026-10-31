"""Phase 3: assemble the S2 tables (results/p3_tables.md + results/p3_summary.json) and charts."""
import numpy as np
import pandas as pd

from common import CAL, FIG, REAL, RESULTS, SCORES, SIM, load_json, plot_style, save_json

META = {
    "llama3.2:3b": ("Llama (Meta)", "Llama 3.2 Community License", "https://ollama.com/library/llama3.2"),
    "phi4-mini:3.8b": ("Phi (Microsoft)", "MIT", "https://ollama.com/library/phi4-mini"),
    "gemma3:4b": ("Gemma (Google)", "Gemma Terms of Use", "https://ollama.com/library/gemma3"),
    "granite4:3b": ("Granite (IBM)", "Apache 2.0", "https://ollama.com/library/granite4"),
    "mistral:7b": ("Mistral", "Apache 2.0", "https://ollama.com/library/mistral"),
    "qwen3.5:4b": ("Qwen (Alibaba)", "Apache 2.0", "https://ollama.com/library/qwen3.5"),
    "userlm-8b": ("Llama (Microsoft UserLM, fine-tuned from Llama-3.1-8B)", "MIT (model card); Llama 3.1 base terms: to verify",
                  "https://huggingface.co/microsoft/UserLM-8b (GGUF: bartowski/microsoft_UserLM-8b-GGUF)"),
}


def fmt(x, d=2):
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{d}f}"


def main():
    sp = load_json(RESULTS / "p3_speed_memory.json")
    t1 = load_json(RESULTS / "p3_test1_scores.json")["per_model"] if (RESULTS / "p3_test1_scores.json").exists() else {}
    t2 = load_json(RESULTS / "p3_test2_realism.json")
    t3 = load_json(RESULTS / "p3_test3_scores.json")
    models = [m for m in META if m in sp]
    rows1, rows2, summ = [], [], {}
    for m in models:
        fam, lic, link = META[m]
        s = sp[m]
        d = s.get("details", {})
        r1 = t1.get(m, {})
        rows1.append(f"| {m} | {fam} | {d.get('parameter_size', '?')} | {d.get('quantization_level') or ('Q4_K_M (pulled tag)' if m == 'userlm-8b' else '?')} | "
                     f"{s['ollama_ps_vram_mib']} MiB alone; with qwen2.5:3b: {'fits' if s['fits_next_to_qwen2.5_3b'] else 'does NOT fit'} "
                     f"({s['coload_nvidia_smi_used_mib']} MiB used) | {r1.get('realism', 'n/a')} | {r1.get('role', 'n/a')} | "
                     f"{s['sec_per_message']} | {lic} | {link} |")
        r2 = t2.get(m, {})
        r3 = t3.get(m, {})
        cv, cs = r3.get("conv", {}), r3.get("csat", {})
        ct, st = cv.get("test_chosen", {}), cs.get("test_chosen", {})
        rd_no = r2.get("noex", {}).get("distance_mean")
        rd_ex = r2.get("ex5", {}).get("distance_mean")
        inv = [x for x in (cv.get("invalid_json_rate_v2"), cs.get("invalid_json_rate_v2")) if x is not None]
        unp = [x for x in (cv.get("unparseable_rate_v2"), cs.get("unparseable_rate_v2")) if x is not None]
        br = [x for x in (cv.get("breaks_role_rate_v2"), cs.get("breaks_role_rate_v2"), r2.get("ex5", {}).get("breaks_role_rate"),
                          r2.get("noex", {}).get("breaks_role_rate")) if x is not None]
        rows2.append(f"| {m} | {fmt(rd_no, 3)} | {fmt(rd_ex, 3)} | {cs.get('chosen_on_dev', 'n/a')} | {fmt(st.get('mae'))} | "
                     f"{fmt(st.get('spearman'))} | {fmt(st.get('qwk'))} | {cv.get('chosen_on_dev', 'n/a')} | {fmt(ct.get('mae'))} | "
                     f"{fmt(ct.get('spearman'))} | {fmt(ct.get('qwk'))} | {fmt(np.mean(inv) if inv else None, 3)} | "
                     f"{fmt(np.mean(unp) if unp else None, 3)} | {fmt(np.mean(br) if br else None, 3)} |")
        summ[m] = {"family": fam, "licence": lic, "speed_s_per_msg": s["sec_per_message"], "vram_mib": s["ollama_ps_vram_mib"],
                   "fits_with_qwen": s["fits_next_to_qwen2.5_3b"], "test1": r1, "realism_noex": rd_no, "realism_ex5": rd_ex,
                   "csat_test": st, "conv_test": ct, "csat_qwk": st.get("qwk"), "conv_qwk": ct.get("qwk"),
                   "score_match_qwk_mean": np.mean([x for x in (st.get("qwk"), ct.get("qwk")) if x is not None]) if st else None,
                   "invalid_json": np.mean(inv) if inv else None,
                   "unparseable": np.mean(unp) if unp else None}
    b = t3
    base = []
    for name in ("csat", "conv"):
        for k, v in b[f"baseline_{name}"].items():
            base.append(f"| {name.upper()} | {k} | {v['n']} | {fmt(v['mae'])} | {fmt(v['spearman'])} | {fmt(v['qwk'])} | "
                        f"{fmt(v['exact_acc'])} | {fmt(v['within1_acc'])} | {fmt(v['macro_f1'])} | {fmt(v['wasserstein'])} |")
    md = ["## Table 1 (team format)",
          "| Model | Family | Size | Quantization | GPU memory | Realism (0-6) | Stays in role (0-6) | Seconds per message | Licence | Link |",
          "|---|---|---|---|---|---|---|---|---|---|", *rows1, "",
          "## Table 2 (against real data; Test 3 numbers on the test samples, version chosen on dev)",
          "| Model | Realism distance, no examples | Realism distance, 5 real examples | CSAT version | CSAT MAE | CSAT Spearman | CSAT QWK | CONV version | CONV MAE | CONV Spearman | CONV QWK | invalid-JSON rate, strict (v2) | score unparseable (v2) | breaks-role rate |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|", *rows2, "",
          "## Baselines on the same test samples",
          "| Set | Baseline | n | MAE | Spearman | QWK | exact | +-1 | macro-F1 | Wasserstein |", "|---|---|---|---|---|---|---|---|---|---|", *base]
    (RESULTS / "p3_tables.md").write_text("\n".join(md), encoding="utf-8")
    save_json(summ, RESULTS / "p3_summary.json")
    charts(models, t3)
    print("\n".join(md))


def charts(models, t3):
    plt = plot_style()
    for name, title in (("csat", "CSAT (customer scores)"), ("conv", "CONV (annotator scores)")):
        ms = [m for m in models if name in t3.get(m, {})]
        if not ms:
            continue
        ncol = 4
        nrow = -(-len(ms) // ncol)
        fig, axes = plt.subplots(nrow, ncol, figsize=(13, 3.0 * nrow), sharey=True, squeeze=False)
        flat = axes.ravel()
        for ax in flat[len(ms):]:
            ax.axis("off")
        for ax, m in zip(flat, ms):
            r = t3[m][name]
            real = r["test_v2_before_calibration"]["true_dist"]
            before = r["test_v2_before_calibration"]["pred_dist"]
            after = r["test_v3_after_calibration"]["pred_dist"]
            n = sum(real.values())
            x = np.arange(5)
            w = 0.27
            ax.bar(x - w, [real[str(s)] / n for s in SCORES], w, color=REAL, label="real")
            ax.bar(x, [before[str(s)] / n for s in SCORES], w, color=SIM, label="simulated (v2)")
            ax.bar(x + w, [after[str(s)] / n for s in SCORES], w, color=CAL, label="simulated + calibration (v3)")
            ax.set_xticks(x, SCORES)
            ax.set_title(m, loc="left", fontsize=9)
        for row in axes:
            row[0].set_ylabel("share of test items")
        h, lab = flat[0].get_legend_handles_labels()
        if len(ms) < len(flat):
            flat[-1].legend(h, lab, fontsize=9, frameon=False, loc="center")
        else:
            fig.legend(h, lab, fontsize=8, frameon=False, loc="upper right")
        fig.suptitle(f"{title}: real vs simulated score distribution (test)", x=0.01, ha="left", fontsize=11, fontweight="bold")
        fig.tight_layout()
        fig.savefig(FIG / f"real_vs_sim_{name}.png")


if __name__ == "__main__":
    main()
