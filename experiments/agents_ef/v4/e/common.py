"""Agent E v4 - shared helpers (manifests, per-queue outcome tracking, the urgent-capacity shield, policy factory).

Nothing in v3/ is modified: v4 imports the frozen v3 simulator and wraps it.

WHY each piece exists (short):
- manifests(): NEW day sets. V3 TEST (seeds 900000+) was already inspected, so it can no longer be a clean final test.
  DEV  = seeds 700_000+ (refinement / selection, all 13 families, labelled).
  TEST4 = seeds 1_300_000+ (NEW confirmatory test, frozen by SHA256, used once after pre-registration).
  Seed blocks are disjoint from TRAIN (0..199_999), V3 VAL (500_000+) and V3 TEST (900_000+).
- EnvV4: identical dynamics and reward to EnvV3 (it only ADDS bookkeeping): it counts, per step, how many queue-C
  tickets ended as SLA miss / lost, so a constrained (Lagrangian) objective can be trained and diagnosed. The
  optional `lam_c` adds  -lam_c * (queue-C failures this step) / F_ref  to the TRAINING reward only.
  The evaluation return is ALWAYS the unchanged v3 equal-weight return (never altered to favour RL).
- UrgentShield: a classical rule (Erlang-C, textbook staffing) computes how many sessions queue C needs right now.
  It turns that into a STRONGER MASK: actions that would leave queue C below that floor are removed, and while C is
  below the floor only actions that raise C stay allowed (if any exists). The RL policy still chooses inside the
  shielded mask (argmax of its Q-values). IMPORTANT: a mask constrains ALLOCATION only; it cannot guarantee future
  SLA (arrivals are random, service takes 6 min while the SLA is 5 min, a HIGH ticket's SLA is only 3 min).
"""

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[2]          # experiments/agents_ef
sys.path.insert(0, str(HERE))
from baselines.heuristics import erlang_c_wait_prob  # noqa: E402
from env.callcenter_env import A_ACT, A_DEACT, A_FB_OFF, A_FB_ON, A_KEEP, MOVES, N_ACTIONS, N_Q  # noqa: E402
from v3.e.env_v3 import ConfigV3, EnvV3  # noqa: E402
from v3.e.scenarios_v3 import HELDOUT_FAMILIES, TRAIN_FAMILIES  # noqa: E402

E4 = Path(__file__).resolve().parent
V3E = HERE / "v3" / "e"
CFG = E4 / "configs"
QC = 2                                               # index of queue C (urgent)
SEED0 = {"dev": 700_000, "test4": 1_300_000}
DAYS_PER_FAMILY = {"dev": 8, "test4": 50}


# ------------------------------------------------------------------------------------------------ manifests
def build_manifest(split: str) -> dict:
    fams = TRAIN_FAMILIES + HELDOUT_FAMILIES
    s0, n = SEED0[split], DAYS_PER_FAMILY[split]
    env = EnvV3()
    days = []
    for k, f in enumerate(fams):
        for i in range(n):
            seed = s0 + 1000 * k + i
            tp = env.build_tape(seed, f)
            days.append({"day_id": f"{split}-{f}-{i:03d}", "family": f, "seed": seed,
                         "heldout_family": f in HELDOUT_FAMILIES, "rho": tp["spec"].rho, "arrivals": int(len(tp["q"]))})
    return {"split": split, "days_per_family": n, "families": fams, "train_families": TRAIN_FAMILIES,
            "heldout_families": HELDOUT_FAMILIES, "seed_rule": f"seed = {s0} + 1000*family_index + i", "days": days}


def write_manifest(split: str):
    path = CFG / f"{split}_manifest.json"
    if path.exists():
        raise SystemExit(f"{path} exists: manifests are write-once")
    body = json.dumps(build_manifest(split), indent=1)
    path.write_text(body)
    (CFG / f"{split}_manifest.sha256").write_text(hashlib.sha256(body.encode()).hexdigest() + "\n")
    return path


def load_manifest(split: str) -> list[dict]:
    """split in {dev, test4} (v4 manifests, hash-checked) or {val} (the frozen v3 VAL manifest)."""
    d = CFG if split in SEED0 else V3E / "configs"
    body = (d / f"{split}_manifest.json").read_text()
    want = (d / f"{split}_manifest.sha256").read_text().strip()
    if hashlib.sha256(body.encode()).hexdigest() != want:
        raise SystemExit(f"{split} manifest hash mismatch: refusing to use it")
    return json.loads(body)["days"]


# ------------------------------------------------------------------------------------------------ env wrapper
class EnvV4(EnvV3):
    """EnvV3 + per-queue outcome counters (+ optional Lagrangian term on queue-C failures, TRAINING ONLY)."""

    def __init__(self, cfg: ConfigV3 | None = None, families=None, lam_c: float = 0.0):
        super().__init__(cfg, families)
        self.lam_c = float(lam_c)

    def reset(self, *a, **kw):
        out = super().reset(*a, **kw)
        self._qid = self.tape["q"]
        self._prev_fail = np.zeros(N_Q, int)
        self.c_fail_day = 0
        return out

    def queue_failures(self) -> np.ndarray:
        """Cumulative failures (SLA miss, abandoned, left at day end) per queue so far."""
        bad = self.status >= 2
        return np.bincount(self._qid[bad], minlength=N_Q)

    def step(self, action: int):
        obs, r, done, trunc, info = super().step(action)
        f = self.queue_failures()
        step_fail = f - self._prev_fail
        self._prev_fail = f
        info["queue_fail"] = step_fail
        c_fail = int(step_fail[QC])
        self.c_fail_day += c_fail
        info["reward_env"] = r                         # the unchanged v3 reward (what every evaluation uses)
        if self.lam_c:
            r = r - self.lam_c * c_fail / self.cfg.ref_fail_per_step
        return obs, r, done, trunc, info


# ------------------------------------------------------------------------------------------------ urgent shield
def _erlang_need(lam_per_min: float, svc_min: float, sla_min: float, target: float, cap: int) -> int:
    """Fewest sessions k with P(wait > sla) = C(k, a) * exp(-(k*mu - lam) * sla) <= target (M/M/k, Erlang C)."""
    if lam_per_min <= 0:
        return 0
    mu = 1.0 / svc_min
    a = lam_per_min / mu
    k = max(1, int(np.floor(a)) + 1)
    while k < cap and erlang_c_wait_prob(k, a) * np.exp(-(k * mu - lam_per_min) * sla_min) > target:
        k += 1
    return k


def alloc_after(env, a: int) -> np.ndarray:
    """Allocation that action a would produce (same rules as EnvV3._apply, without touching env)."""
    alloc = env.alloc.copy()
    if 1 <= a <= 12:
        i, j = MOVES[a - 1]
        alloc[i] -= 1
        alloc[j] += 1
    elif a == A_ACT:
        alloc[int(np.argmax(env._load()))] += 1
    elif a == A_DEACT:
        load = env._load()
        cand = [q for q in range(N_Q) if alloc[q] > (env.cfg.min_alloc_urgent if q == QC else 0)]
        alloc[min(cand, key=lambda q: load[q])] -= 1
    return alloc


class UrgentShield:
    """Dynamic minimum capacity for queue C from Erlang C on the CURRENT forecast + backlog.

    floor_C = max(min_alloc_urgent, need_C(target)), capped by `max_floor`. The shielded mask:
      - removes every action that would bring alloc_C below floor_C (if alloc_C is already >= floor_C);
      - if alloc_C < floor_C: keeps only actions that INCREASE alloc_C (moves into C, or activate when the
        activation would go to C), when at least one is valid; otherwise it only removes actions lowering C.
    `target` = allowed probability of waiting longer than the queue-C SLA (lower = more protective).
    """

    def __init__(self, target: float = 0.2, max_floor: int = 8, sla_min: float | None = None, static: int | None = None):
        self.target, self.max_floor, self.sla_min = target, max_floor, sla_min
        self.static = static                         # static=k -> plain "stronger mask": queue C always >= k

    def floor(self, env) -> int:
        c = env.cfg
        if self.static is not None:
            return int(self.static)
        backlog_c = len(env.queue[QC]) if hasattr(env, "queue") else len(env.waiting[QC])
        lam = (float(env.ewma[QC]) + backlog_c / 3.0) / c.step_min
        sla = self.sla_min if self.sla_min is not None else float(env.sla[QC])
        need = _erlang_need(lam, float(env.svc[QC]), sla, self.target, c.max_sessions)
        return int(min(max(c.min_alloc_urgent, need), self.max_floor))

    def mask(self, env, base_mask: np.ndarray) -> tuple[np.ndarray, dict]:
        fl = self.floor(env)
        cur = int(env.alloc[QC])
        after_c = np.array([alloc_after(env, a)[QC] if base_mask[a] else -1 for a in range(N_ACTIONS)])
        m = base_mask.copy()
        if cur < fl:
            up = base_mask & (after_c > cur)
            if up.any():
                m = up
            else:
                m = base_mask & (after_c >= cur)
            reason = f"queue C below urgent floor ({cur} < {fl})"
        else:
            m = base_mask & (after_c >= fl)
            reason = ""
        if not m.any():                                  # can never happen (keep keeps alloc), defensive
            m = base_mask.copy()
        return m, {"floor_c": fl, "alloc_c": cur, "reason": reason}


# ------------------------------------------------------------------------------------------------ RL loading
def find_run(run_id: str) -> Path:
    for root in (E4 / "runs", V3E / "runs"):
        if (root / run_id / "run.json").exists():
            return root / run_id
    raise FileNotFoundError(run_id)


def load_agent(run_id: str, which: str = "best.pt"):
    import torch
    from rl.agents import make_agent
    torch.set_num_threads(1)
    run = find_run(run_id)
    info = json.loads((run / "run.json").read_text())
    if info.get("status") != "done":
        raise SystemExit(f"run not done: {run_id}")
    ag = make_agent(info["algo"], EnvV3.obs_dim, EnvV3.n_actions, info["seed"], hidden=tuple(info["hidden"]))
    ag.load_state_dict(torch.load(run / which, map_location="cpu", weights_only=False))
    return ag, info, run


def q_values(agent, obs) -> np.ndarray:
    import torch
    with torch.no_grad():
        return agent.q(torch.as_tensor(obs).unsqueeze(0))[0].numpy()


def masked_argmax(q, mask) -> int:
    return int(np.argmax(np.where(mask, q, -1e9)))


def file_sha256(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
