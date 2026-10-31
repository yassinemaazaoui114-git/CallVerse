"""End-to-end style-RL demo, offline (no LLM, no API): message -> decision -> bandit style -> writer -> Agent F
(correctness + satisfaction) -> reward -> bandit update. Run: python scripts/run_rl_demo.py [episodes]
Feedback is SIMULATED (callverse/learning/simulator.py). Uses models/agent_f/stacker_candidate.pkl if present
(response-aware candidate), else the fixed text + delay predictor.
"""
import pickle
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from callverse.data.atlas.seed import seed as seed_atlas          # noqa: E402
from callverse.data.seed import seed as seed_shopnova              # noqa: E402
from callverse.learning.simulator import make_personas, make_situations, record_for   # noqa: E402
from callverse.learning.style_policy import StylePolicy            # noqa: E402
from callverse.quality.reward import evaluate_response             # noqa: E402
from callverse.quality.satisfaction import MODEL_DIR               # noqa: E402


def main(episodes: int = 30):
    seed_shopnova(); seed_atlas()
    cand = MODEL_DIR / "stacker_candidate.pkl"
    stacker = pickle.loads(cand.read_bytes()) if cand.exists() else False
    print("satisfaction model:", "style candidate (simulated-trained)" if stacker else "fixed text + delay")
    sits, personas, rng, policy = make_situations(), make_personas(4, 303, "demo"), random.Random(0), StylePolicy(seed=0)
    for i in range(episodes):
        s, p = rng.choice(sits), rng.choice(personas)
        probe = record_for(s, p, "short", None, rng)
        style = policy.choose(probe["situation"])
        rec = record_for(s, p, style, None, rng)
        out = evaluate_response(rec, stacker=stacker)
        policy.update(rec["situation"], style, out["reward"])
        print(f"{i:02d} {rec['company']:8} {s['reason']:20} {p['emotion']:8} {style:18} "
              f"sat={out['satisfaction']:.2f} {out['correctness']:7} reward={out['reward']}  sim_rating={rec['rating']}")
    print("\nlearned arms:")
    for g, arms in policy.summary().items():
        print(" ", g, {s: v["p"] for s, v in arms.items()})


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 30)
