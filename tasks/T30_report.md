# T30 report — RL5: the style policy (bandit), built now; real ratings plug in later

**Top line:** the style policy, its log, the offline training, the rating importer and the pipeline switch are built and
tested. The switch is **OFF by default**, and with it off the output is byte-identical to main. Every learning result
below uses a **SYNTHETIC** reward. Real learning starts once the team returns a valid ratings file.
Tests: **1876/1876** (main 1848, +28). Regression with the switch OFF: **72/72**, 0 wrong writes, 0 leaks (bar ≥ 70/72). Switch-ON spot check: 12/12, decisions unchanged.

## 1. In plain words
CallVerse can now learn how to word a reply (short, warm, or warm with a closing line). It cannot change what the reply
decides. It tries the styles, remembers which one scored best for each kind of situation, and slowly picks the better
one more often. Nothing is real yet: the team's ratings file had six identical tabs, so the importer rejects it.
Agent F gives every style the same score, so it cannot teach anything either. The learning was therefore shown on a
made-up ("synthetic") world. When real ratings arrive, two commands import them and train the policy. No new code is
needed.

## 2. Done
- `callverse/learning/style_policy.py`: Thompson sampling with Beta posteriors and rewards scaled to 0..1. There is
  one bandit per group (company, outcome class approve/decline/ask/info/other, emotion class angry/other). With
  fewer than 5 observations in a group, it tries the least-tried style. Other parts: `choose`, `update`, `best`,
  `best_per_group`, JSON `save`/`load` (`out/rl5_policy.json`; a missing file means it explores), seedable `rng`,
  and the fallback `DEFAULT_STYLE = "warm"`.
- `style_log` table in the tickets DB (`callverse/tickets/store.py`). Columns: situation JSON, group, style, reply,
  reward, `source` = real / predicted / synthetic, ticket id, and both clocks. `CREATE TABLE IF NOT EXISTS` makes an
  old DB file gain the table (tested). New functions: `add_style_log`, `set_style_reward`, `style_log`.
- `callverse/learning/rewards.py`:
  - `from_agent_f`: a FAIL gives 0, otherwise (satisfaction − 1) / 4. The module says this reward ignores the style.
  - `constant_across_styles`: detects a reward that is the same for every style.
  - `from_ratings`: reads the RL1 xlsx with the standard library only (no new package) or a one-rater CSV, then maps
    each letter to its style(s) through `out/rl1_rating_key.json`. It **rejects** a file with identical tabs, one
    value everywhere, or no stars.
  - `synthetic` / `FLAT_MEANS`.
- `scripts/train_style_policy.py`:
  - Options: `--source synthetic|ratings|agent_f`, `--n`, `--seed`, `--replies cached|slm|none`, `--db`,
    `--no-log`, `--baselines`.
  - Situations: the 27 RL1 situations, rebuilt from the run traces. It reads run OUTPUT files only and never opens
    the locked message files. Their 3 cached SLM replies are used by default.
  - Outputs: `out/rl5_curve.csv` and `out/rl5_policy.json`.
  - Ratings mode uses offline replay: a round counts only when that situation was rated in the chosen style.
- `scripts/import_ratings.py <file> [--dry-run]`: checks the file, then saves one style_log row per rating with
  `source=real`.
- Pipeline switch, in `pipeline.final_reply` (`policy_style`, `log_policy_style`):
  - It runs only if `learning.style_policy` is true, no style is already set (decision / env var / `slm.reply_style`)
    and the reply is not the off-topic redirect.
  - It sets only `decision["reply_style"]`. The choice is traced (`style_policy`) and logged in style_log with an
    empty reward.
  - Any error leads to no style plus a `style_policy_error` trace.
- `config.yaml`: new block `learning: {style_policy: false, style_policy_file: out/rl5_policy.json}`.
- README (T30 line + the import commands), `docs/DEMO_RUNBOOK.md` (one line: the policy is OFF).
- Step 9 (Console "Learning" page) was **not done**. It was optional, and I kept the time for the regression.

## 3. Evidence
- **pytest 1876/1876** (`tests/test_t30_style_policy.py`, 28 tests). They cover:
  - groups;
  - exploration before 5 observations;
  - convergence on the synthetic world (warm for angry, short for calm);
  - seeding and save/load;
  - the flat world;
  - style_log, including an old DB file;
  - the agent F constant warning;
  - rating mapping, including one letter shown for 2 styles;
  - **identical-tabs rejection** (a synthetic copy of the 6-tab file), one-value rejection, empty file;
  - import then train on ratings;
  - the pipeline switch: off is identical, on sets only the style, a trained policy is used, an existing style wins,
    a policy error gives no style, a style_log error never breaks the reply;
  - bandit beats random and the worst fixed style.
- **OFF = byte-identical to main.** I ran `final_reply` on 10 decisions (8 ShopNova status, 1 damaged item,
  1 Atlas redirect), each twice: once with the SLM down (template) and once with a fixed fake SLM. That is 20
  outputs, run on a main worktree (8db7e8d) and on this branch. Same sha256 `6ef197c4…0465`.
- **The real first ratings file** (`out/CallVerse_reply_rating_filled.xlsx`):
  `python -m scripts.import_ratings … --dry-run` gives
  `REJECTED: all 6 rater tabs are identical (Yassine, Dali, Semah, Mahmoud, Molka, Ayoub) …`.
- **Agent F as the reward source** (60 rounds): `WARNING: reward constant across styles -> nothing to learn`.
  Example: s02 scores 0.4247 for all 3 styles. p05 scores 0 for every style because correctness FAILs: its refund
  facts are re-read from today's DB.
- **Baselines (SYNTHETIC reward, made-up world)**, `out/rl5_baselines.md`. Setup: 300 rounds × 3 seeds, the 27 RL1
  situations (5 angry, 22 other).

  | strategy (synthetic) | mean reward | regret |
  |---|---|---|
  | always short | 0.703 | 0.097 |
  | always warm | 0.543 | 0.257 |
  | always warm_next_step | 0.609 | 0.191 |
  | random | 0.628 | 0.172 |
  | **bandit** | **0.681** | **0.119** |

  - At 300 rounds the bandit beats random and the worst fixed style, but not "always short". Most situations are calm,
    and exploring 13 groups costs rounds.
  - With a longer run (same world, nothing tuned) the bandit wins. At 1000 rounds: bandit 0.738 vs short 0.705. At
    3000: 0.767 vs 0.712, with regret 0.033.
  - Flat world (all styles 0.6): no crash, every strategy at 0.59–0.61.
- **Synthetic training run:** `--source synthetic --n 300 --seed 1 --db out/rl5_synthetic.db` writes 300 style_log rows
  labelled `synthetic`. The policy is copied to `out/rl5_policy_synthetic.json`. Angry groups learned warm /
  warm_next_step; calm groups learned short.
- **Regression (switch OFF, local models, `out/t30_run72.sh`): 72/72. Bar (≥ 70/72, 0 wrong writes, 0 leaks) met.**
  The first run was stopped by the system for low memory after 36 messages. The other 36 were re-run later
  (the 3 finished lines commented out in `out/t30_run72.sh`). `out/t30_compare.py` compares all six files with T29:

  | set | now | T29 |
  |---|---|---|
  | decline_practice | 12/12 | 12 |
  | decline_heldout | 12/12 | 12 |
  | t14b_practice | 12/12 | 12 |
  | t14c_practice | 12/12 | 12 |
  | t14c_heldout | 12/12 | 12 |
  | t14d_heldout | 12/12 | 12 |

  - `TOTAL 72/72 wrong_writes=0 crashes=0 leaks=0 api_calls=0 avg=18.9s max=25.7s` (`out/t30_compare.txt`).
  - No message changed decision or pass state against T29. Groq tokens 0 (local models only).
  - Output files `out/t30_<set>.json` / `.log`.
- **Spot check with the switch ON** (`out/t30_spot_on.py`, synthetic policy `out/rl5_policy_synthetic.json`, the 12
  t14b_practice messages; `config.yaml` stays OFF):
  - `12/12 passed · crashes 0 · leaks 0 · wrong writes 0 · Groq tokens 0`.
  - `policy calls 12, styles set 10, decision unchanged 12/12` (`out/t30_spot_on_checks.json`). The policy changed only
    `reply_style`. The 2 calls without a style (T-0011, T-0012) already had no group.
  - Styles chosen: short 6, warm_next_step 4 (the 2 angry groups, approve and other/other).
  - Decisions are the same as the switch-OFF run of the same 12 messages: 12/12.
- **DBs:** `shopnova.db` and `atlas.db` were put back from `out/t30_dbbackup/` after the runs (`cmp` identical).
  `callverse.db` was not put back: it holds the imported ratings (section 7).
- **Held-out C/D file:** committed unchanged (git blob `eb994bf…`, the same before and after). It was never run and
  only read (step 1 below).
- The diff has nothing under `models/` or `data/raw/`, and no secrets.

## 4. Problems
- **Low memory (7.7 GB PC).** The 72-message run had to be split in two because the system stopped the first run.
  Close other apps before model runs.
- **`style_log` has 783 rows labelled `real`, not 483.** The 300 extra rows (written 17:07, before the step 8 runs)
  seem to come from the `--source ratings` training run. If a later training reads all `real` rows, these replay rows
  could be counted twice (see Q5).
- **No real reward yet.** Everything learned so far is synthetic. Agent F ignores the style, because its
  style-aware model (`stacker.pkl`) is not promoted.
- **Thompson sampling is not "near-uniform" on the flat world** (the task asked for this). A style with bad early luck
  gets tried less: in one seed of 600 rounds, a 9 / 204 / 387 split. This costs nothing there, because all styles
  pay the same. The test checks "no crash, every style tried ≥ 5 times, no reward lost" instead of uniformity.
- **Few ratings per group.** 27 situations over 13 groups, and some groups have one situation. Even with 6 real raters
  most groups stay thin. The `MIN_OBS` exploration plus the default style covers this, but the result per group will
  be noisy.
- **The emotion class differs from the task wording** (see Q1).
- The pipeline's style_log rows have an empty reward, and nothing links a later star rating back to a live ticket's
  row yet. Only the RL1 sheet ratings can be imported today.

## 5. Questions for the Brain
1. **Emotion class.** The task says "angry-negative / other". If a negative sentiment counted as angry, 24 of the 27
   situations would be "angry" and the split would mean nothing. I used **anger or disgust only** (5 of 27). It is one
   constant (`ANGRY_EMOTIONS`). Keep it this way, or include negative sentiment?
2. **Held-out C/D, D07 (expectation problem).** `promote: [4]` with Smart Watch stock 60. `AgentD.scan` proposes only
   the top `MAX_PROMOTIONS_PER_SCAN = 3` overstocked products, sorted by stock (`callverse/agents/agent_d.py:23`,
   sort at `:69`, `[:3]` at `:74`). The seeded DB has 505 overstocked products, with top stocks 120 / 80 / 80, so
   product 4 at 60 is never proposed. D07 fails whatever the model does. Options: expect product 4 in the overstock
   list, raise its stock above 120, or drop the case. Also, its text says "~3 sold" but the data says 4 in 30 days.
3. **Held-out C/D, C12 (weak test).** `act: any`, and `propose_hold` is not in `must_not_call`, so a 10-day hold
   proposal passes the bench. Only the Coordinator would send it back, and the outcome is not scored. Should
   `propose_hold` go in `must_not_call`?
4. Minor: C08 says "wedding is on Friday", and sim_today (2026-10-09) is a Friday: today or the 16th? This is not
   scored. `tests/dev/agents_cases.json` `about` calls the file `agents_heldout.json`, not `agents_heldout_cd.json`.
   The other 9 cases (C08–C11, C13, C14, D05, D06, D08) match the seed data, the P20 rules and the scorer format.
5. **Replay rows labelled `real`.** Training with `--source ratings` appears to add its 300 replay rounds to
   `style_log` as `real` (483 → 783 rows). Should these rows get their own label (e.g. `replay`) so only true ratings
   count as `real`? I did not change this (outside step 8).

## 6. Next step
When the team returns a ratings file with one tab per rater, run:
`python -m scripts.import_ratings <file>`, then `python -m scripts.train_style_policy --source ratings`.
Then compare with the baselines on the real rows. Then decide on the Brain's answers to Q2/Q3 before the single
held-out C/D run. Optional later: the Console "Learning" page (step 9).

Merge line for Yassine (after the Brain's review): `git checkout main && git merge --no-ff feat/t30-rl5`

## 7. Update — real ratings imported and trained (2 Nov, after 15:40)
The team's new file `out/CallVerse_reply_rating_filled.xlsx` passed the importer's checks (tabs differ, values spread).
- Import: **483 of 483** ratings saved in `style_log` with `source = real`. Raters: Yassine 80, Dali 81, Semah 81,
  Mahmoud 81, Molka 81, Ayoub 79. The tickets DB was backed up first (`out/t30_dbbackup/callverse.db`).
- Training: `python -m scripts.train_style_policy --source ratings`, 300 rounds, seed 1, 27 situations, 13 groups.
  The policy is in `out/rl5_policy.json` (git-ignored).
- **REAL** result (mean reward per style, 0..1 = (stars − 1) / 4):

| Group | n | short | warm | warm_next_step | Best |
|---|---|---|---|---|---|
| atlas / approve / other | 9 | 0.25 | 0.583 | 0.75 | warm_next_step |
| atlas / ask / other | 17 | 0.333 | 0.688 | 0.583 | warm |
| atlas / decline / angry | 8 | 0.25 | 0.75 | 1.0 | warm_next_step |
| atlas / decline / other | 77 | 0.312 | 0.6 | 0.801 | warm_next_step |
| atlas / info / other | 11 | 0.0 | 0.312 | 0.6 | warm_next_step |
| atlas / other / other | 10 | 0.375 | 0.8 | 0.667 | warm |
| shopnova / approve / other | 22 | 0.333 | 0.75 | 0.956 | warm_next_step |
| shopnova / ask / angry | 15 | 0.125 | 0.625 | 0.679 | warm_next_step |
| shopnova / ask / other | 33 | 0.125 | 0.583 | 0.607 | warm_next_step |
| shopnova / decline / angry | 18 | 0.333 | 0.438 | 0.75 | warm_next_step |
| shopnova / decline / other | 23 | 0.0 | 0.583 | 0.833 | warm_next_step |
| shopnova / info / angry | 11 | 0.083 | 0.5 | 1.0 | warm_next_step |
| shopnova / info / other | 46 | 0.25 | 0.5 | 0.868 | warm_next_step |

- What it says: the team prefers `warm_next_step` in 11 of 13 groups and `warm` in 2 (Atlas ask, Atlas other).
  `short` is last in every group. The groups are small (8–77 rows): read the 2 `warm` groups as weak evidence.
- The pipeline switch stays **OFF** by default; turning it on is a decision for the Brain / Yassine.
- Still open from section 3/4: the 72-message regression (36/72 done, all pass) and the switch-ON spot check.
