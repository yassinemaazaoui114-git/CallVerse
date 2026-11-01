# F1 report — Review and accept Semah's agent F

Branch: `review/agent-f` (from `main` 68b36d3). Semah's branch `origin/feature/agent-f-rlhf-e2e` (0bfba47) was only read.
No merge, no Groq, no live run.

## In plain words
Agent F guesses how happy a customer will be (1 to 5 stars), and its correctness check says if a reply is right
(PASS / FAIL / UNKNOWN). We took only these two parts from Semah's branch, plus their tests and the scripts that build
F's model; the style-learning (RL) code stays on his branch as reference. His 14 tests pass here and all other tests
still pass. The trained model file is **not on this PC** (it is git-ignored and was never shared), so the check on
50–100 reviews and the speed measures could not be done: by the task's stop rule I stopped there. The Amazon reviews
used to train F have a licence problem to decide (non-commercial only, and Amazon has withdrawn the data).

## Done
- Step 0: `git fetch --all`; tree clean (only untracked `.vscode/`, `tasks/F1_accept_agent_f.md`, `tasks/RL2b_followup.md`);
  `review/agent-f` created from `main`.
- Step 1: inventory below (37 files on his branch).
- Step 2: 13 files brought in with `git checkout origin/feature/agent-f-rlhf-e2e -- <path>` (the "take" rows). Nothing in
  the pipeline, Coordinator, Intake or a pinned file changed; nothing imports `callverse.quality` yet.
- Step 3: his tests run with `.venv` python.
- Step 4: two sections added to `DATA_LICENCES.md` (Amazon reviews; Olist delay table + "no pretrained model").
- `requirements.txt`: `scikit-learn>=1.5` added (F needs it; it was already installed in `.venv`: 1.9.1, scipy 1.18.1).
- `README.md`: Agent F line under Benchmarks, `quality/` and `benchmarks/agent_f/` in Folders.
- Steps 5–6: **not done** (model file missing, see Problems).

### Inventory (`git diff --stat main...origin/feature/agent-f-rlhf-e2e`; size = lines added)
| path | what it is | size | take / leave |
|---|---|---|---|
| `callverse/quality/__init__.py` | F package | 1 | **take** |
| `callverse/quality/satisfaction.py` | F model + inference (`predict_satisfaction`) | 117 | **take** |
| `callverse/quality/reward.py` | F correctness check + dual reward (`evaluate_response`) | 201 | **take** |
| `tests/test_satisfaction.py` | F tests (contract, text/delay, stacker, eval metrics) | 51 | **take** |
| `tests/test_agent_f_reward.py` | correctness / reward tests | 79 | **take** |
| `benchmarks/agent_f/__init__.py` | package | 0 | **take** |
| `benchmarks/agent_f/common.py` | data script: Amazon download + candidate models | 41 | **take** |
| `benchmarks/agent_f/benchmark.py` | model choice on validation (+ `metrics`, used by train / eval) | 72 | **take** |
| `benchmarks/agent_f/train.py` | trains `models/agent_f/satisfaction.pkl`, test once | 36 | **take** |
| `benchmarks/agent_f/evaluate_rated.py` | eval on rated conversations (imported by the tests) | 40 | **take** |
| `benchmarks/agent_f/olist_delay.py` | data script: Olist delay table | 33 | **take** |
| `benchmarks/agent_f/results/benchmark.json` | his validation results | 45 | **take** |
| `benchmarks/agent_f/results/test_eval.json` | his Amazon test result | 21 | **take** |
| `callverse/learning/*` (4 files) | style bandit, simulator, style writer, RL inference | 711 | leave (RL1 reference) |
| `benchmarks/agent_f/compare_satisfaction.py` | stacker fit on SIMULATED ratings | 113 | leave (RL) |
| `benchmarks/agent_f/train_style.py`, `evaluate_style_candidate.py` | style reward training / check | 239 | leave (RL) |
| `benchmarks/agent_f/rl_eval.py`, `policy_eval.py`, `persona_scale_eval.py` | RL evaluations | 404 | leave (RL / RL5) |
| `benchmarks/agent_f/results/{rl_eval,policy_eval,persona_scale_eval,satisfaction_models}.json` | RL results | 956 | leave |
| `tests/test_rl_pipeline.py`, `tests/test_agent_f_style_training.py` | RL tests (import `callverse.learning`) | 344 | leave |
| `scripts/run_rl_demo.py` | RL demo entry point | 42 | leave |
| `docs/agent_f.md` | model card, mixed F + RL sections | 179 | leave (key facts copied here) |
| `docs/agent_f_style_reward.md` | style reward notes | 63 | leave |
| `tasks/RL3_report.md` | his report | 56 | leave |
| `.gitignore` (`data/simulated/`) | for simulated RL data | 1 | leave (not needed by F) |
| `requirements.txt` (`scikit-learn`) | dependency | 3 | taken by hand (own comment) |
| `README.md` | link to `docs/agent_f.md` | 1 | leave (own README lines) |

No UI, voice, Docker or web-channel file is on the branch.

### How F is called
- `callverse.quality.satisfaction.predict_satisfaction(record, model=None, stacker=None) -> {"score": float}`, score
  clipped to **[1, 5]**, 3 decimals. Input `record` = conversation record: `messages` (list of `{role, text}`; only
  `role == "user"` texts are read), `situation.days_late` (optional), `style` and `situation.emotion` (only used by the
  optional stacker). Score = expected stars of the text model, blended 0.5 / 0.5 with the Olist delay mean when
  `days_late` is known. If `models/agent_f/stacker.pkl` exists it is used instead (it does not exist; `stacker=False`
  turns it off).
- `callverse.quality.reward.evaluate_response(record, **kw) -> {"satisfaction": float, "correctness": "PASS"|"FAIL"|"UNKNOWN",
  "reward": 1|-1|None, "train": bool, "evidence": [str]}`. Extra input: `record["decision"]` (Coordinator decision,
  `docs/decision_format.md`) and `company`; the reply checked is `record["reply"]` or the last assistant message.
  Reward: PASS and satisfaction ≥ 4 → +1; PASS and < 4 → −1; FAIL → −1; UNKNOWN → None (not trained on).
- RL interface file: **not in the repo** (no `RL_interface_spec.md` in `docs/`, no `claude/` folder; his doc says it was
  shared by upload only). So I could not compare; the signatures above are the contract his code states.

## Evidence
- His tests: `tests/test_satisfaction.py` + `tests/test_agent_f_reward.py` → **14 passed / 14** (3.4 s). No paid API,
  no model file needed (they train a tiny model inside the test).
- Full suite on `review/agent-f`: **1297 passed / 1297** (`python -m pytest -q --ignore=tests/data`, 141 s).
- Olist delay table rebuilt offline (`python -m benchmarks.agent_f.olist_delay`): on time 4.22 (n=1801), ≤2 d 3.07 (27),
  ≤5 d 2.50 (32), ≤10 d 1.57 (35), >10 d 1.40 (48) — **same as `DELAY_TABLE`** in the code.
- His numbers (from his committed JSON, **not re-run by me**): validation MAE 0.638 (TF-IDF + logreg, chosen) vs
  predict-mean baseline 1.20; Amazon test n=5000, expected-stars output: MAE 0.605 rounded / 0.644 raw, Spearman 0.80,
  within ±1 92 %; 2.1 ms mean, 3.4 ms p95 per prediction; model file 18.6 MB (his doc).
- Step 5 (50–100 human reviews) and step 6 (size / RAM / ms on this PC): **not measured** — `models/agent_f/` does not
  exist on this PC and no `satisfaction.pkl` / `stacker*.pkl` is anywhere under the user folder; `data/raw/amazon_reviews_multi_en/`
  does not exist either.

## Problems
1. **Model file missing** (stop rule). F cannot score anything here yet. It can be rebuilt with
   `python -m benchmarks.agent_f.train` (his doc: about 2–3 min CPU, 60k reviews), but that is training **on this PC**
   plus a download, which CLAUDE.md does not allow ("Training runs on Colab / Kaggle") — so I did not do it.
2. **Licence.** The SetFit mirror says Apache-2.0, but the data is Amazon's Multilingual Amazon Reviews Corpus:
   **non-commercial research use only**, and Amazon has **withdrawn** it (original HF dataset marked "defunct ... due to
   the decision of data providers"). University use fits the original terms; using a mirror after the withdrawal is
   unclear. Flagged in `DATA_LICENCES.md`.
3. **Which 50–100 human reviews?** Amazon test (5,000) was already read once by Semah, so it is not "unseen" for a
   new check, but it was not used to train. The Olist sample in the repo has its review texts removed, and the raw
   Olist reviews are Portuguese (F is English-only). The team's rated conversations (Notion 31, ~100) are the natural
   set but they are not in the repo.
4. **Domain gap:** F's text model learned product reviews, not support chats; its satisfaction score does not depend on
   the reply (only on the customer's words + delay) unless a stacker is promoted. For RL1 this means the reward does not
   change with the reply style yet.
5. `predict_satisfaction` silently loads `models/agent_f/stacker.pkl` if someone drops one there (his RL work saves
   `stacker_selected.pkl`, a different name, so today this cannot happen by accident).
6. `reward.py` re-reads facts from the ShopNova / Atlas tools (read only); it does not write.

## Questions for the Brain
1. May I train F once on this PC (≈2–3 min CPU, sklearn), or should Semah share `satisfaction.pkl` (18.6 MB) /
   train it on Colab? Without the file, steps 5–6 cannot run.
2. Licence: accept the Amazon mirror for a university project (flagged), or switch F to another real rated source
   (e.g. TWCS has no stars; the Kaggle support-CSAT set Semah's doc mentions needs a Kaggle login)?
3. For the 50–100 check: use 100 reviews from the Amazon **validation** split (not trained on, but used for model
   choice), the Amazon test split, or the team's rated conversations (please add the file)?
4. RL contract: the RL interface spec is not in the repo; can it be committed to `docs/` so RL1 can be checked against it?

## Next step
Get the model file (Q1) and the review set (Q3), then run steps 5–6 in a short follow-up (F1b):
`python -m benchmarks.agent_f.evaluate_rated <file.jsonl>` gives MAE, within ±1 and the mean baseline; one timing
script for size / RAM / ms. Then RL1 can use `evaluate_response(record)["reward"]` as its reward.
