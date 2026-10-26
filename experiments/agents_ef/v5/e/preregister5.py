"""Write the TEST5 pre-registration (configs/preregistration5.json + .md) and FREEZE the comparison set.

    python -m v5.e.preregister5          (refuses to overwrite; refuses if any TEST5 row exists)
Input: configs/prereg5_candidates.json (written by hand from DEV / DEVSHIFT evidence, see NOTEBOOK).
Everything the confirmatory analysis does is fixed here BEFORE any TEST5 row exists: comparison set with checkpoint
SHA256, reference, primary metric, Holm family, safety acceptance rule (margins), lower tail, per-family and
runtime reporting. evaluate_v5 --split test5 only runs policies listed here; analyze_test5 only runs this analysis.
"""

import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from v5.e.common5 import CFG, E5, UNSEEN, file_sha256, find_run, load_manifest  # noqa: E402
from v3.e.scenarios_v3 import HELDOUT_FAMILIES  # noqa: E402


def runs_of(spec):
    tail = spec.split("|")[-1]
    kind, _, arg = tail.partition(":")
    return None if kind == "rule" else arg


def main():
    out = CFG / "preregistration5.json"
    if out.exists():
        raise SystemExit("pre-registration exists: it is write-once")
    t5 = E5 / "results" / "eval_test5"
    if t5.exists() and list(t5.glob("*.csv")):
        raise SystemExit("TEST5 rows already exist: cannot pre-register after the fact")
    spec = json.loads((CFG / "prereg5_candidates.json").read_text())
    days = load_manifest("test5")
    hashes = {}
    for g, specs in spec["groups"].items():
        for s in specs:
            r = runs_of(s)
            if r:
                p = find_run(r) / "best.pt"
                hashes[s] = {"run": r, "checkpoint": str(p.relative_to(E5.parents[1])), "best_pt_sha256": file_sha256(p)}
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    pr = {"frozen_at_utc": now, "test_manifest": "v5/e/configs/test5_manifest.json",
          "test_manifest_sha256": (CFG / "test5_manifest.sha256").read_text().strip(), "n_days": len(days),
          "families": sorted({d["family"] for d in days}), "heldout_families": HELDOUT_FAMILIES,
          "unseen_shift_families": UNSEEN, "days_per_family": 50,
          "seeds_rule": "seed = 1700000 + 1000*family_index + i (16 families x 50)",
          **{k: spec[k] for k in ("reference_group", "groups", "primary_comparisons", "secondary_comparisons",
                                  "constraints", "decision_rule", "roles", "notes") if k in spec},
          "reference": spec["groups"][spec["reference_group"]][0],
          "policies_all": sorted({s for v in spec["groups"].values() for s in v}),
          "checkpoint_hashes": hashes,
          "primary_metric": "equal-weight return per day (unchanged v3 reward), higher is better, all 800 days",
          "analysis": ("paired two-level bootstrap (v3/e/analyze_v3.boot_diff: resample training seeds within each group, "
                       "the SAME resampled days for both groups), 4000 resamples, 95 % percentile CIs; Holm correction over "
                       "the primary return comparisons (bootstrap two-sided p); safety acceptance = paired CI lower bounds "
                       "of queue-C SLA and HIGH SLA differences vs the reference above minus the margins AND zero hard-"
                       "constraint violations (invalid proposals executed, HIGH on fallback, budget overrun days); lower "
                       "tail = CVaR10 % of the seed-averaged daily return, paired bootstrap; per family (16) and per "
                       "block (in-distribution / held-out / unseen-shift) descriptive differences; runtime = decision "
                       "latency p50/p95 from the evaluator."),
          "exploratory_vs_confirmatory": ("Everything before this file (V3 VAL, DEV, DEVSHIFT) is exploratory. Only the "
                                          "analysis above on TEST5 is confirmatory; anything else on TEST5 is labelled exploratory.")}
    out.write_text(json.dumps(pr, indent=1))
    md = ["# Agent E V5 — pre-registration of the confirmatory TEST5 evaluation", "",
          f"- **Frozen at (UTC): {now}** — before any TEST5 row exists (evaluate_v5 refuses TEST5 before this file).",
          f"- TEST5 manifest: `{pr['test_manifest']}`, SHA256 `{pr['test_manifest_sha256']}`, {len(days)} days "
          f"(16 families × 50: 8 in-distribution, 5 held-out {', '.join(HELDOUT_FAMILIES)}, 3 unseen-shift {', '.join(UNSEEN)}).",
          f"- Reference: `{pr['reference']}`.", f"- Primary metric: {pr['primary_metric']}.", "",
          "## Comparison set (frozen)", "", "| Group | Role | n | First spec |", "|---|---|---|---|"]
    for g, specs in pr["groups"].items():
        md.append(f"| {g} | {pr.get('roles', {}).get(g, '')} | {len(specs)} | `{specs[0]}` |")
    md += ["", "## Safety acceptance rule", ""] + [f"- {k}: {v}" for k, v in pr["constraints"].items()]
    md += ["", "## Primary comparisons (Holm-corrected)", ""] + [f"- {g} − reference" for g in pr["primary_comparisons"]]
    md += ["", "## Decision rule", "", pr["decision_rule"], "", "## Analysis", "", pr["analysis"], "",
           pr["exploratory_vs_confirmatory"], "", "## Checkpoint hashes", ""]
    md += [f"- `{s}`: `{h['best_pt_sha256']}`" for s, h in hashes.items()]
    if pr.get("notes"):
        md += ["", "## Notes", "", pr["notes"]]
    (CFG / "preregistration5.md").write_text("\n".join(md) + "\n")
    print("frozen at", now, "policies:", len(pr["policies_all"]))


if __name__ == "__main__":
    main()
