"""Recompute the equal-cost gaps of a generalization.json from its saved curves and per-seed summaries, with the
no-extrapolation rule of bench/generalize_e.py.  python -m bench.generalize_gaps <generalization.json>..."""

import json
import sys
from pathlib import Path

from bench.generalize_e import gap_stats, interp_gap

for path in sys.argv[1:]:
    d = json.loads(Path(path).read_text())
    for c in d["conditions"].values():
        for v in c["rl"].values():
            for x in v["seeds"]:
                x["gap_vs_forecast"] = interp_gap(x, c["heuristic_curves"]["forecast"])
                x["gap_vs_erlang_c"] = interp_gap(x, c["heuristic_curves"]["erlang_c"])
            v["gap_vs_forecast"] = gap_stats(v["seeds"], "gap_vs_forecast")
            v["gap_vs_erlang_c"] = gap_stats(v["seeds"], "gap_vs_erlang_c")
    Path(path).write_text(json.dumps(d, indent=2))
    print("recomputed", path)
