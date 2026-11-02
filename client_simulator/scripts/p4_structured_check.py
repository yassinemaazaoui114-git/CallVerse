"""Phase 4 check: does Ollama structured output (JSON schema, used by the kit) change the raw scores the calibration
map was fitted on? Runs the v2 CSAT prompt on the dev sample with format=schema and compares with the unconstrained run.
python p4_structured_check.py MODEL..."""
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import RESULTS, load_json, save_json, score_metrics  # noqa: E402
from llm import cached_chat, parse_score, short, unload_all  # noqa: E402
from p3_tests import DEFAULT_N, SC_OPTS, collect, csat_card, samples  # noqa: E402
from simulator.prompts import SCORE_SCHEMA, score_messages  # noqa: E402


def main(models):
    rub = load_json(RESULTS / "p3_rubrics_from_train.json")
    S = samples(DEFAULT_N)
    dev = S[("csat", "dev")].to_dict("records")
    cal = load_json(Path(__file__).resolve().parents[1] / "simulator" / "calibration.json")["models"]
    out = {}
    for m in models:
        def run(r):
            msgs = score_messages(csat_card(r), None, "v2", rubric=rub["csat"], shots=rub["csat"]["shots"])
            return cached_chat("p4_structured", m, "s2-schema", r["id"], msgs, num_ctx=6144, fmt=SCORE_SCHEMA, **SC_OPTS)
        with ThreadPoolExecutor(4) as ex:
            res = list(ex.map(run, dev))
        schema = [parse_score(x["text"]) for x in res]
        free = collect(m, "csat", "v2", "dev", S).set_index("id").raw.fillna(5).astype(int)
        real = [r["score"] for r in dev]
        raw_schema = [s[0] or 5 for s in schema]
        raw_free = [free[r["id"]] for r in dev]
        mp = cal[m]["map"]
        out[short(m)] = {
            "n": len(dev), "valid_json_with_schema": float(np.mean([s[2] for s in schema])),
            "same_raw_score_share": float(np.mean(np.array(raw_schema) == np.array(raw_free))),
            "dev_unconstrained_calibrated": score_metrics(real, [mp[str(x)] for x in raw_free]),
            "dev_schema_calibrated": score_metrics(real, [mp[str(x)] for x in raw_schema]),
        }
        print(short(m), {k: v for k, v in out[short(m)].items() if not isinstance(v, dict)},
              round(out[short(m)]["dev_unconstrained_calibrated"]["qwk"], 3), round(out[short(m)]["dev_schema_calibrated"]["qwk"], 3))
    save_json(out, RESULTS / "p4_structured_output_check.json")
    unload_all()


if __name__ == "__main__":
    main(sys.argv[1:])
