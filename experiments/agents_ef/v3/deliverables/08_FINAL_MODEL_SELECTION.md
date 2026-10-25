# 08 — Final model selection

Selection follows rules written before TEST (`03_BENCHMARK_PROTOCOL.md`; F: `v3/f/PROTOCOL.md`). TEST is used to **confirm or refute**, never to choose.

## Agent E

**Rule.** Pick the policy with the best VAL return. A learned policy replaces the classical one only if it is significantly better on the locked TEST.

**On VAL**
- Fluid MPC k = 0.5 is best: −178.3.
- Best RL group mean: Dueling DQN −184.0, Dueling DDQN −186.7. Those are each run's best checkpoint, so they flatter RL.

**On TEST**
- No RL policy is significantly better than MPC.
- The guarded Dueling DDQN ties: +4.1 [−0.9, +8.2].

**Selected Agent E policy: Fluid MPC (k = 0.5)**
- 6-step lookahead over the 17 valid actions, with the same objective and the same action mask.
- 0 parameters, 2.25 / 5.17 ms per decision.
- Fully explainable: every proposal can be justified by its predicted queue costs.

**Equally good simpler alternative: Forecast (z = 0.25)**
- −1.6 [−3.5, +0.4] vs MPC: a tie.
- 0.06 ms per decision, no lookahead; it is the cheapest per day (1,600).
- Use it if MPC's lookahead cannot be explained or maintained.

**Research candidate, not selected: guarded Forecast + Dueling DDQN** (8.1k params, 35 KB, 0.29 ms)
- It ties on return, is 4% cheaper, and is better on severe overload.
- It is worse on queue C (−9.5 pp) and on lost customers (+0.27 pp).
- It needs training and has seed variance, for no significant gain.
- Keep it for the "where could RL add value" discussion: allocation under overload.

**Why not pure RL**
- Pure DDQN ties at best (−3.7, leaning worse).
- PPO, Tabular Q, DQN, Double DQN and Dueling DQN are worse than MPC.

## Agent F (M7)

### Satisfaction scorer

**Rule** (Worker F, VAL only): among the models within one seed-SD of the best fine-tuned VAL MAE, take the smallest and fastest.

**Default: TF-IDF + Ridge on the last 256 tokens**
- 0.19M params, milliseconds per prediction.
- Best on VAL overall (0.395); TEST 0.392, Spearman 0.596.
- Best on ZH, and tied on EN.
- A simpler model competes with, and here beats, the transformers.

**Neural, multilingual: e5-small vocabulary-trimmed, 6 layers, 256 tokens** (seed 1)
- 17.4M params, 71.8 MB (int8: 39.5 MB), 58 ms (int8: 41 ms) on CPU.
- TEST 0.399 ± 0.006; EN 0.296 (the best EN TEST MAE).
- Needed if languages or vocabulary beyond the training corpora matter; on Amazon EN/FR, the e5 family beats TF-IDF by 0.2 MAE.
- `model.pt` SHA256 `466c0cc8…`, `model_int8.pt` SHA256 `78908a2b…`.
- Path: `f_v3/ckpt/e5small_trim_ft_L6_frac0.5_len256_s1/` (outside git; `v3/f/checkpoints_manifest.json`).

**Wiring.** M7 currently loads the e5 checkpoint (`--scorer f:<dir>`). A TF-IDF scorer wrapper for M7 is a small next step; the TF-IDF model is not yet saved as a loadable predictor.

### Quality, rule audit, reports

Deterministic checks (`v3/m7/`), no model. They were selected because each check has an exact definition in the prototype.

### Feedback to E

**Gated; current verdict: KPI only.** Agent E's selected policy uses no F signal.

## Decision for the Brain

1. Agent E = MPC or Forecast. The tie means either is defensible; MPC is the measured best on VAL.
2. Agent F scorer = TF-IDF or e5-L6/256.
