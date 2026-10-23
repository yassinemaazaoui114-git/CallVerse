"""Shared-model experiment for Agents E (M6) and F (M7): does ONE tiny backbone serve both tasks?

Shared input space (why sharing is not forced): both agents reason about the STATE OF A SERVICE QUEUE.
A service-state encoder g maps one queue's 6 features (arrivals, backlog, mean/p90 waiting age, allocation,
utilisation) + queue one-hot (4) -> 32-d vector.
  E (Dueling Double DQN): g applied to each of the 4 queues -> concat + 7 global features -> Q-values (17 actions).
  F-lite (CSAT regression): g(queue state when the request was served) + 3 ticket features + 64-d text features
                            (TF-IDF -> SVD, fitted on F-train) -> CSAT.
Architectures (same layer sizes, same E budget 150k env steps, same number of F updates, same seeds):
  A separate: g_E and g_F independent.
  B shared:   one g, trained on TD-loss(E) + lambda * MSE(F) together (multi-task).
  C hybrid:   F-lite trained first; E reuses F's encoder FROZEN and trains only its own layers (transfer).
E is scored on the held-out TEST days, F-lite on the held-out TEST rows; choices (checkpoint) on VAL only.

    python -m shared.multitask --arch shared --seed 0 --out results/shared
"""

import argparse
import copy
import json
import resource
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_f.benchmark import load, metrics  # noqa: E402
from bench.evaluation import SPLITS, evaluate, summarize  # noqa: E402
from env.callcenter_env import N_Q, REWARD_PRESETS, CallCenterEnv, EnvConfig  # noqa: E402

NEG = -1e9
ONEHOT = torch.eye(N_Q)


class Encoder(nn.Module):
    """g: one queue's service state (6) + queue one-hot (4) -> 32."""

    def __init__(self, d=32):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(10, d), nn.Tanh(), nn.Linear(d, d), nn.Tanh())

    def forward(self, x):
        return self.net(x)


class EHead(nn.Module):
    """E: g on each queue -> concat with global features -> dueling Q-values."""

    def __init__(self, n_actions, d=32):
        super().__init__()
        self.body = nn.Sequential(nn.Linear(N_Q * d + 7, 64), nn.Tanh())
        self.v, self.a = nn.Linear(64, 1), nn.Linear(64, n_actions)

    def forward(self, g, obs):
        blocks = obs[:, :6 * N_Q].reshape(-1, N_Q, 6)
        x = torch.cat([blocks, ONEHOT.expand(obs.shape[0], N_Q, N_Q)], -1)
        h = self.body(torch.cat([g(x).flatten(1), obs[:, 6 * N_Q:]], -1))
        a = self.a(h)
        return self.v(h) + a - a.mean(-1, keepdim=True)


class FHead(nn.Module):
    """F-lite: g(queue state at service time) + ticket features (3) + text (64) -> CSAT."""

    def __init__(self, d=32, d_text=64):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(d + 3 + d_text, 64), nn.ReLU(), nn.Linear(64, 1))

    def forward(self, g, ctx, tick, text):
        return self.net(torch.cat([g(ctx), tick, text], -1)).squeeze(-1) + 4.0


def n_params(*mods):
    seen, n = set(), 0
    for m in mods:
        for p in m.parameters():
            if id(p) not in seen:
                seen.add(id(p))
                n += p.numel()
    return n


def f_tensors(rows, svd, vec):
    ctx = torch.tensor([r["state"] + list(np.eye(N_Q)[r["queue"]]) for r in rows], dtype=torch.float32)
    tick = torch.tensor([[min(r["wait_min"] / r["sla_min"], 5.0), float(r["fallback"]), float(r["abandoned"])]
                         for r in rows], dtype=torch.float32)
    text = torch.tensor(svd.transform(vec.transform([r["text"] for r in rows])), dtype=torch.float32)
    y = torch.tensor([r["csat"] for r in rows], dtype=torch.float32)
    return ctx, tick, text, y


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arch", choices=["separate", "shared", "hybrid"], required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--steps", type=int, default=150_000)
    ap.add_argument("--lam", type=float, default=1.0, help="weight of F's loss in the shared model")
    ap.add_argument("--out", default="results/shared")
    a = ap.parse_args()
    torch.set_num_threads(1)
    torch.manual_seed(a.seed)
    rng = np.random.default_rng(a.seed)
    t_start = time.perf_counter()

    # ---------------- F data (simulated) and fixed text features (fitted on F-train only)
    from sklearn.decomposition import TruncatedSVD
    from sklearn.feature_extraction.text import TfidfVectorizer
    tr, va, te = load("train"), load("val"), load("test")
    vec = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True).fit([r["text"] for r in tr])
    svd = TruncatedSVD(64, random_state=0).fit(vec.transform([r["text"] for r in tr]))
    Ftr, Fva, Fte = f_tensors(tr, svd, vec), f_tensors(va, svd, vec), f_tensors(te, svd, vec)

    # ---------------- networks
    env = CallCenterEnv(EnvConfig(**REWARD_PRESETS["balanced"]), scenarios=SPLITS["train"]["scenarios"])
    g_e = Encoder()
    g_f = g_e if a.arch == "shared" else Encoder()
    e_head, f_head = EHead(env.n_actions), FHead()
    gamma, batch, lr = 0.97, 128, 5e-4

    def f_loss(idx):
        ctx, tick, text, y = (t[idx] for t in Ftr)
        return F.mse_loss(f_head(g_f, ctx, tick, text), y)

    def f_eval(T):
        with torch.no_grad():
            return f_head(g_f, *T[:3]).numpy()

    # C (hybrid): F first, then freeze its encoder for E
    n_f_updates = 0
    if a.arch == "hybrid":
        opt_f = torch.optim.Adam(list(g_f.parameters()) + list(f_head.parameters()), lr=lr)
        for _ in range(36_000):                       # same number of F updates as in A/B (~steps/4 - starts/4)
            idx = torch.as_tensor(rng.integers(0, len(Ftr[3]), batch))
            loss = f_loss(idx)
            opt_f.zero_grad()
            loss.backward()
            opt_f.step()
            n_f_updates += 1
        g_e = copy.deepcopy(g_f)
        for p in g_e.parameters():
            p.requires_grad_(False)

    e_params = [p for p in list(g_e.parameters()) + list(e_head.parameters()) if p.requires_grad]
    if a.arch == "shared":
        opt = torch.optim.Adam(list(g_e.parameters()) + list(e_head.parameters()) + list(f_head.parameters()), lr=lr)
    else:
        opt = torch.optim.Adam(e_params, lr=lr)
        opt_f = torch.optim.Adam(list(g_f.parameters()) + list(f_head.parameters()), lr=lr) \
            if a.arch == "separate" else None

    def q_values(net_g, head, obs):
        return head(net_g, obs)

    g_t, h_t = copy.deepcopy(g_e), copy.deepcopy(e_head)            # target network
    cap, D = 100_000, env.obs_dim
    O, O2 = np.zeros((cap, D), np.float32), np.zeros((cap, D), np.float32)
    A_, R_, DN = np.zeros(cap, np.int64), np.zeros(cap, np.float32), np.zeros(cap, np.float32)
    M2 = np.zeros((cap, env.n_actions), bool)
    ptr = size = steps = 0
    lo, hi = SPLITS["train"]["seed_range"]
    val_env = CallCenterEnv(EnvConfig(**REWARD_PRESETS["balanced"]), scenarios=SPLITS["val"]["scenarios"])

    def policy(env_, obs, mask):
        with torch.no_grad():
            q = q_values(g_e, e_head, torch.as_tensor(obs).unsqueeze(0))[0].numpy()
        return int(np.argmax(np.where(mask, q, NEG)))

    best_val, best_state, curve = -1e9, None, []
    while steps < a.steps:
        obs, info = env.reset(seed=int(rng.integers(lo, hi + 1)))
        mask, done = info["action_mask"], False
        while not done:
            eps = max(0.05, 1.0 - 0.95 * steps / 60_000)
            act = int(rng.choice(np.flatnonzero(mask))) if rng.random() < eps else policy(env, obs, mask)
            obs2, r, done, _, info = env.step(act)
            O[ptr], A_[ptr], R_[ptr], O2[ptr], DN[ptr], M2[ptr] = obs, act, r, obs2, float(done), info["action_mask"]
            ptr, size = (ptr + 1) % cap, min(size + 1, cap)
            obs, mask = obs2, info["action_mask"]
            steps += 1
            if steps >= 5_000 and steps % 4 == 0:
                i = rng.integers(0, size, batch)
                o, o2 = torch.as_tensor(O[i]), torch.as_tensor(O2[i])
                m2 = torch.as_tensor(M2[i])
                with torch.no_grad():
                    a2 = q_values(g_e, e_head, o2).masked_fill(~m2, NEG).argmax(1, keepdim=True)  # double DQN
                    qn = q_values(g_t, h_t, o2).masked_fill(~m2, NEG).gather(1, a2).squeeze(1)
                    target = torch.as_tensor(R_[i]) + gamma * (1 - torch.as_tensor(DN[i])) * qn
                q = q_values(g_e, e_head, o).gather(1, torch.as_tensor(A_[i]).unsqueeze(1)).squeeze(1)
                loss = F.smooth_l1_loss(q, target)
                fidx = torch.as_tensor(rng.integers(0, len(Ftr[3]), batch))
                if a.arch == "shared":
                    loss = loss + a.lam * f_loss(fidx)          # one backbone, two losses
                    n_f_updates += 1
                opt.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_([p for grp in opt.param_groups for p in grp["params"]], 10.0)
                opt.step()
                if a.arch == "separate":
                    lf = f_loss(fidx)
                    opt_f.zero_grad()
                    lf.backward()
                    opt_f.step()
                    n_f_updates += 1
            if steps % 2000 == 0:
                g_t.load_state_dict(g_e.state_dict())
                h_t.load_state_dict(e_head.state_dict())
            if steps % 15_000 == 0:
                s = summarize(evaluate(policy, "val", val_env))
                f_mae = metrics(Fva[3].numpy(), f_eval(Fva))["mae"]
                curve.append({"step": steps, "e_val_ret": s["ret"], "f_val_mae": f_mae})
                if s["ret"] > best_val:
                    best_val = s["ret"]
                    best_state = copy.deepcopy((g_e.state_dict(), e_head.state_dict(), g_f.state_dict(),
                                                f_head.state_dict()))
    train_s = time.perf_counter() - t_start

    # ---------------- final scores with the VAL-chosen checkpoint
    g_e.load_state_dict(best_state[0])
    e_head.load_state_dict(best_state[1])
    if a.arch != "shared":
        g_f.load_state_dict(best_state[2])
    f_head.load_state_dict(best_state[3])
    times = []
    e_test = summarize(evaluate(policy, "test", decision_times=times))
    f_lat = []
    for k in range(200):
        t1 = time.perf_counter()
        f_eval(tuple(t[k:k + 1] for t in Fte))
        f_lat.append(time.perf_counter() - t1)
    res = {"arch": a.arch, "seed": a.seed, "lam": a.lam, "steps": steps, "f_updates": n_f_updates,
           "train_s": round(train_s, 1),
           # C: E's encoder is an exact frozen copy of F's -> deployed once, counted once
           "params_total_unique": n_params(g_f, e_head, f_head) if a.arch == "hybrid" else n_params(g_e, e_head, g_f, f_head),
           "params_e": n_params(g_e, e_head), "params_f_lite": n_params(g_f, f_head),
           "e_test": e_test, "f_test": metrics(Fte[3].numpy(), f_eval(Fte)),
           "f_val": metrics(Fva[3].numpy(), f_eval(Fva)),
           "e_decision_ms_p50": round(1e3 * float(np.median(times)), 4),
           "f_predict_ms_p50": round(1e3 * float(np.median(f_lat[20:])), 4),
           "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
           "curve": curve, "note": "simulator + simulated data; F-lite text = TF-IDF->SVD64 (no TinyBERT)"}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{a.arch}_s{a.seed}.json").write_text(json.dumps(res, indent=2))
    torch.save(best_state, out / f"{a.arch}_s{a.seed}.pt")
    print(json.dumps({k: res[k] for k in ("arch", "seed", "train_s", "params_total_unique")}
                     | {"e_ret": round(e_test["ret"], 2), "e_sla": round(e_test["sla_pct"], 2),
                        "f_mae": round(res["f_test"]["mae"], 4), "f_f1": round(res["f_test"]["f1_macro_3class"], 4)}))


if __name__ == "__main__":
    main()
