"""Write the TEST4 pre-registration (configs/preregistration.json + .md) and FREEZE the candidates.

    python -m v4.e.preregister            (refuses to overwrite an existing pre-registration)
Everything the confirmatory analysis will do is fixed here BEFORE any TEST4 row exists: the comparison set (with
checkpoint SHA256 hashes), primary metric, constraints with margins, reference, seeds, days, statistics.
evaluate_v4 --split test4 only runs policies listed here; analyze_v4 test4 only runs this analysis.
"""

import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from v4.e.common import CFG, E4, file_sha256, find_run, load_manifest  # noqa: E402
from v3.e.scenarios_v3 import HELDOUT_FAMILIES  # noqa: E402

SPEC = json.loads((CFG / "prereg_candidates.json").read_text())      # written by hand from DEV evidence


def run_of(spec):
    tail = spec.split("|")[-1]
    kind, _, arg = tail.partition(":")
    if kind == "rule":
        return None
    if kind == "hier":
        arg = arg.partition(":")[2]
    return arg


def main():
    out = CFG / "preregistration.json"
    if out.exists():
        raise SystemExit("pre-registration exists: it is write-once")
    if list((E4 / "results" / "eval_test4").glob("*.csv")) if (E4 / "results" / "eval_test4").exists() else False:
        raise SystemExit("TEST4 rows already exist: cannot pre-register after the fact")
    days = load_manifest("test4")
    groups, hashes = {}, {}
    for g, specs in SPEC["groups"].items():
        groups[g] = specs
        for s in specs:
            r = run_of(s)
            if r:
                hashes[s] = {"run": r, "best_pt_sha256": file_sha256(find_run(r) / "best.pt")}
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    pr = {"frozen_at_utc": now, "test_manifest": "v4/e/configs/test4_manifest.json",
          "test_manifest_sha256": (CFG / "test4_manifest.sha256").read_text().strip(), "n_days": len(days),
          "families": sorted({d["family"] for d in days}), "heldout_families": HELDOUT_FAMILIES,
          "days_per_family": 50, "seeds_rule": "seed = 1300000 + 1000*family_index + i (13 families x 50)",
          "reference_group": SPEC["reference_group"], "reference": SPEC["groups"][SPEC["reference_group"]][0],
          "groups": groups, "policies_all": sorted({s for v in groups.values() for s in v}),
          "checkpoint_hashes": hashes, "primary_metric": "equal-weight return per day (unchanged v3 reward), higher is better",
          "primary_comparisons": SPEC["primary_comparisons"], "secondary_comparisons": SPEC.get("secondary_comparisons", []),
          "constraints": SPEC["constraints"], "decision_rule": SPEC["decision_rule"],
          "analysis": ("paired two-level bootstrap (v3/e/analyze_v3.boot_diff: resample training seeds within each group, "
                       "the SAME resampled days for both groups), 4000 resamples, 95 % percentile CIs; Holm correction over "
                       "the primary return comparisons; constraint = lower CI bound of the paired difference vs the "
                       "reference above minus the margin; safety violations counted exactly (must be 0)."),
          "exploratory_vs_confirmatory": ("Everything before this file (V3 VAL, DEV) is exploratory. Only the analysis "
                                          "above on TEST4 is confirmatory. Anything else computed on TEST4 is labelled exploratory."),
          "notes": SPEC.get("notes", "")}
    out.write_text(json.dumps(pr, indent=1))
    md = [f"# Agent E V4 — pre-registration of the confirmatory TEST4 evaluation", "",
          f"- **Frozen at (UTC): {now}** — written before any TEST4 row exists (evaluate_v4 refuses TEST4 before this file).",
          f"- TEST4 manifest: `{pr['test_manifest']}`, SHA256 `{pr['test_manifest_sha256']}`, {len(days)} days "
          f"(13 families × 50; held-out families never used in training: {', '.join(HELDOUT_FAMILIES)}).",
          f"- Reference: `{pr['reference']}` (best rule on V3 VAL; not re-tuned).",
          f"- Primary metric: {pr['primary_metric']}.", "", "## Comparison set (frozen)", "",
          "| Group | Policies (seeds) |", "|---|---|"]
    for g, specs in groups.items():
        md.append(f"| {g} | {len(specs)}: `{specs[0]}`{' …' if len(specs) > 1 else ''} |")
    md += ["", "## Constraints (non-inferiority vs the reference, paired 95 % CI lower bound)", ""]
    for k, v in pr["constraints"].items():
        md.append(f"- {k}: {v}")
    md += ["", "## Primary comparisons (Holm-corrected)", ""] + [f"- {g} − reference" for g in pr["primary_comparisons"]]
    md += ["", "## Decision rule", "", pr["decision_rule"], "", "## Analysis", "", pr["analysis"], "",
           pr["exploratory_vs_confirmatory"], "", "## Checkpoint hashes", ""]
    for s, h in hashes.items():
        md.append(f"- `{s}`: `{h['best_pt_sha256']}`")
    if pr["notes"]:
        md += ["", "## Notes", "", pr["notes"]]
    (CFG / "preregistration.md").write_text("\n".join(md) + "\n")
    print("frozen at", now, "policies:", len(pr["policies_all"]))


if __name__ == "__main__":
    main()
