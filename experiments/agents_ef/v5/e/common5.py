"""Agent E v5 - shared helpers: shifted / domain-randomised environment, manifests, checkpoint loading.

Nothing in v3/ or v4/ is modified: EnvV5 subclasses v4's EnvV4 (which subclasses the frozen EnvV3).

EnvV5 = EnvV4 (identical dynamics and reward, per-queue failure bookkeeping) + an optional per-day SHIFT:
    shift = {"rho_mult": float, "shape_knots": [4 floats] | None, "svc_mult": [4], "pat_mult": [4],
             "extra_spikes": [[queue, start, end, mult], ...], "extra_failure": [start, end, sessions] | None,
             "base_family": str}
  - svc_mult multiplies the TRUE service time of each queue for the whole day (like the 'slowdown' family, it is
    NOT visible in the observation: the controller only sees its consequences, as in a real centre).
  - pat_mult multiplies each queue's patience (abandonment times).
  - rho_mult / shape_knots / extra_spikes / extra_failure change the exogenous day spec BEFORE the tape is built,
    so every policy evaluated on the same (seed, shift) still faces exactly the same world (common random numbers).
A shift is either given explicitly (manifest days: env.pending_shift = day["shift"] before reset) or, in
DOMAIN-RANDOMISATION training, drawn from the ranges of configs/dr_ranges.json with a generator seeded by the day
seed (reproducible). Without a shift EnvV5 == EnvV4 == EnvV3 (tested).

Day sets (all seed blocks disjoint from TRAIN 0..199,999, V3 VAL 500,000+, V4 DEV 700,000+, V3 TEST 900,000+,
TEST4 1,300,000+):
  devshift: 760,000 + 1000*k + i  - 8 TRAIN families x 6 days with shifts drawn from the DR TRAINING ranges
            (= the "validation distribution" of domain randomisation; DEV-level, used for selection).
  test5:    1,700,000 + 1000*k + i - 13 V3 families + 3 UNSEEN-SHIFT families (ranges outside the DR training
            ranges, configs/dr_ranges.json "unseen_test_shifts"), 50 days each. Write-once, SHA256-frozen.
"""

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[2]          # experiments/agents_ef
sys.path.insert(0, str(HERE))
from env.callcenter_env import N_Q  # noqa: E402
from v3.e.scenarios_v3 import HELDOUT_FAMILIES, TRAIN_FAMILIES, make_spec  # noqa: E402
from v4.e.common import EnvV4, find_run as find_run_v4, load_manifest as load_manifest_v4  # noqa: E402

E5 = Path(__file__).resolve().parent
CFG = E5 / "configs"
RUNS = E5 / "runs"
DR = json.loads((CFG / "dr_ranges.json").read_text())
SEED0 = {"devshift": 760_000, "test5": 1_700_000}
UNSEEN = list(DR["unseen_test_shifts"].keys())


def _u(rng, lo_hi, n=None):
    lo, hi = lo_hi
    return rng.uniform(lo, hi, n) if n else float(rng.uniform(lo, hi))


def draw_shift(rng: np.random.Generator, ranges: dict, base_family: str) -> dict:
    """One shift from a ranges dict (format of configs/dr_ranges.json). All draws from `rng`."""
    sh = {"base_family": base_family, "rho_mult": 1.0, "shape_knots": None, "svc_mult": [1.0] * N_Q,
          "pat_mult": [1.0] * N_Q, "extra_spikes": [], "extra_failure": None}
    if "rho_mult" in ranges:
        sh["rho_mult"] = round(_u(rng, ranges["rho_mult"]), 4)
    if "svc_mult" in ranges:
        sh["svc_mult"] = np.round(_u(rng, ranges["svc_mult"], N_Q), 4).tolist()
    if "svc_mult_common" in ranges:
        sh["svc_mult"] = [round(_u(rng, ranges["svc_mult_common"]), 4)] * N_Q
    if "pat_mult" in ranges:
        sh["pat_mult"] = np.round(_u(rng, ranges["pat_mult"], N_Q), 4).tolist()
    if "pat_mult_common" in ranges:
        sh["pat_mult"] = [round(_u(rng, ranges["pat_mult_common"]), 4)] * N_Q
    st = ranges.get("shape_tilt")
    if st and rng.random() < st["p"]:
        sh["shape_knots"] = np.round(_u(rng, st["knots"], 4), 4).tolist()
    for key, q in (("urgent_spike", 2), ("refund_surge", 1)):
        sp = ranges.get(key)
        if sp and rng.random() < sp["p"]:
            ln = int(rng.integers(sp["len"][0], sp["len"][1] + 1))
            a = int(rng.integers(6, 96 - ln))
            sh["extra_spikes"].append([q, a, a + ln, round(_u(rng, sp["mult"]), 4)])
    fl = ranges.get("failure")
    if fl and rng.random() < fl["p"]:
        ln = int(rng.integers(fl["len"][0], fl["len"][1] + 1))
        a = int(rng.integers(6, 96 - ln))
        sh["extra_failure"] = [a, a + ln, int(rng.integers(fl["sessions"][0], fl["sessions"][1] + 1))]
    return sh


def _apply_spec(spec, sh: dict):
    s = spec
    s.rho = float(np.clip(s.rho * sh["rho_mult"], 0.3, 1.6))
    if sh["shape_knots"] is not None:
        tilt = np.interp(np.linspace(0, 3, 8), np.arange(4), sh["shape_knots"])
        shape = np.asarray(s.shape) * tilt
        s.shape = tuple((shape / shape.mean()).round(4))
    s.spikes = list(s.spikes) + [tuple(x) for x in sh["extra_spikes"]]
    if sh["extra_failure"] is not None and not s.failure:
        s.failure = tuple(sh["extra_failure"])
    return s


class EnvV5(EnvV4):
    """EnvV4 + optional per-day shift (explicit, or domain-randomised with `dr_ranges`)."""

    def __init__(self, cfg=None, families=None, lam_c: float = 0.0, dr_ranges: dict | None = None):
        super().__init__(cfg, families, lam_c)
        self.dr_ranges = dr_ranges
        self.pending_shift = None
        self.shift = None
        self.svc_mult = np.ones(N_Q)

    def reset(self, seed: int = 0, family: str | None = None, spec=None, shift: dict | None = None):
        shift = shift if shift is not None else self.pending_shift
        self.pending_shift = None
        rng = np.random.default_rng(np.random.SeedSequence([int(seed), 5_000_017]))   # shift stream (own)
        if shift is None and self.dr_ranges is not None and spec is None:
            fam = family or self.families[int(rng.integers(len(self.families)))]
            shift = draw_shift(rng, self.dr_ranges, fam)
        if shift is not None:
            fam = shift["base_family"]
            spec = _apply_spec(make_spec(fam, rng), shift)
            family = fam
        self.shift = shift
        self.svc_mult = np.asarray(shift["svc_mult"], float) if shift else np.ones(N_Q)
        out = super().reset(seed=seed, family=family, spec=spec)
        if shift is not None:                               # patience shift: recompute pre-drawn abandonment times
            c, tp = self.cfg, self.tape
            pat = self.patience[tp["q"]] * np.asarray(shift["pat_mult"])[tp["q"]] * (1 - c.patience_emotion_k * tp["emo"])
            self.abandon_at = tp["t_arr"] + c.abandon_grace_min + tp["pat_e"] * pat
        return out

    def _serve(self, q, now, end, slow):
        return super()._serve(q, now, end, slow * float(self.svc_mult[q]))


# ------------------------------------------------------------------------------------------------ manifests
def build_manifest(split: str, days_per_family: int) -> dict:
    s0 = SEED0[split]
    if split == "devshift":
        fams = list(TRAIN_FAMILIES)
    else:
        fams = TRAIN_FAMILIES + HELDOUT_FAMILIES + UNSEEN
    env = EnvV5()
    days = []
    for k, f in enumerate(fams):
        for i in range(days_per_family):
            seed = s0 + 1000 * k + i
            shift = None
            rng = np.random.default_rng(np.random.SeedSequence([seed, 7_700_001]))
            if split == "devshift":
                shift = draw_shift(rng, DR["train_ranges"], f)
            elif f in UNSEEN:
                base = TRAIN_FAMILIES[int(rng.integers(len(TRAIN_FAMILIES)))]
                shift = draw_shift(rng, DR["unseen_test_shifts"][f], base)
            env.pending_shift = shift
            env.reset(seed=seed, family=f if shift is None else None)
            d = {"day_id": f"{split}-{f}-{i:03d}", "family": f, "seed": seed,
                 "heldout_family": f in HELDOUT_FAMILIES, "unseen_shift": f in UNSEEN,
                 "rho": env.spec.rho, "arrivals": int(len(env.tape["q"]))}
            if shift is not None:
                d["shift"] = shift
            days.append(d)
    return {"split": split, "days_per_family": days_per_family, "families": fams,
            "train_families": TRAIN_FAMILIES, "heldout_families": HELDOUT_FAMILIES, "unseen_shift_families": UNSEEN,
            "seed_rule": f"seed = {s0} + 1000*family_index + i", "dr_ranges_sha256": file_sha256(CFG / "dr_ranges.json"),
            "days": days}


def write_manifest(split: str, days_per_family: int):
    path = CFG / f"{split}_manifest.json"
    if path.exists():
        raise SystemExit(f"{path} exists: manifests are write-once")
    body = json.dumps(build_manifest(split, days_per_family), indent=1)
    path.write_text(body)
    (CFG / f"{split}_manifest.sha256").write_text(hashlib.sha256(body.encode()).hexdigest() + "\n")
    return path


def load_manifest(split: str) -> list[dict]:
    """v5 splits (devshift, test5) are hash-checked here; dev / test4 / val come from v4 (hash-checked there)."""
    if split not in SEED0:
        return load_manifest_v4(split)
    body = (CFG / f"{split}_manifest.json").read_text()
    want = (CFG / f"{split}_manifest.sha256").read_text().strip()
    if hashlib.sha256(body.encode()).hexdigest() != want:
        raise SystemExit(f"{split} manifest hash mismatch: refusing to use it")
    return json.loads(body)["days"]


# ------------------------------------------------------------------------------------------------ checkpoints
def find_run(run_id: str) -> Path:
    if (RUNS / run_id / "run.json").exists():
        return RUNS / run_id
    return find_run_v4(run_id)


def load_agent(run_id: str, which: str = "best.pt"):
    """Loads v5 runs (any algo of agents5) and, via the same path, v4 / v3 runs (rl.agents networks)."""
    import torch
    from v5.e.agents5 import make_agent5
    torch.set_num_threads(1)
    run = find_run(run_id)
    info = json.loads((run / "run.json").read_text())
    if info.get("status") != "done":
        raise SystemExit(f"run not done: {run_id}")
    from v3.e.env_v3 import EnvV3
    kw = {"n_quant": info["n_quant"]} if info["algo"].startswith("qr_") else {}
    ag = make_agent5(info["algo"], EnvV3.obs_dim, EnvV3.n_actions, info["seed"], hidden=tuple(info["hidden"]), **kw)
    ag.load_state_dict(torch.load(run / which, map_location="cpu", weights_only=False))
    return ag, info, run


def file_sha256(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
