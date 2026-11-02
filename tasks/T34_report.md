# T34 report — Integrate agent F extras, new login, client simulator, vision

**Top line:** all four branches are in `feat/t34-integrate`.
- Login: merged.
- Vision: merged.
- Simulator: copied, with one adapter.
- Agent F: partly (docs and results only; its RL code stays on its branch).

Results:
- Full suite **2003 passed, 5 skipped** (main 1879).
- Frontend tests 77/77.
- 72-message regression **72/72**: 0 wrong writes, 0 crashes, 0 leaks, 0 API calls, the same as T30.
- The photo model runs on the GPU in 4-bit (nf4).
- With everything loaded, the PC is at its limit: RAM peak 7876 of 7885 MiB, VRAM 5890 of 6141 MiB.

Nothing is merged into main.

## 1. In plain words
We put the team's finished side work into one test branch, on top of main.
- Dali's new sign-in pages are in.
- Mahmoud's simulated customers are in. They can chat with the center and give it a score.
- Semah and Molka's photo check is in. A client can send a photo of a broken item, and the model says what it sees.
- Only Semah's notes on his reply-style learning came in. His code for it uses older names and would clash with the
  reviewed version on main.

Every new part stays quiet unless it is used: with no photo and no simulator, the 72 test messages give exactly the
same results as before. One weak point: when a photo shows damage, Agent B still asks for a photo. The safety rules
then pass the case to a colleague, so nothing wrong is paid.

## 2. Done
Branch `feat/t34-integrate` (from main d1c5909). One commit per step, and a WIP push after each.

| Step | Source | Result | Commit |
|---|---|---|---|
| 1 | `feature/agent-f-rlhf-e2e` (Semah) | **Partly**: docs + result files only | 656437a |
| 2 | `new-login` (Dali) | **Merged** | 02c8c52 |
| 3 | `feature/client-simulator-with-real-data` (Mahmoud) | **Copied** (no common history) + adapter | d3e8073, 7685b8e |
| 4 | `claude/magical-albattani-ktcgao` (Semah's adapter + Molka's channel) | **Merged** | a11cbeb |

**Step 1, agent F.** Conflicts: 5 add/add files, all solved with main's version:
- `callverse/learning/__init__.py`, `callverse/learning/style_policy.py`;
- `callverse/quality/satisfaction.py`, `tests/test_satisfaction.py`;
- `requirements.txt`. No new pins are needed: sklearn, scipy and sentence-transformers are already there.

The only difference in `satisfaction.py` / `test_satisfaction.py` is the style names. The branch has
`apology_first` / `apology_next_step`; main (T30) has `warm` / `warm_next_step`.

Left out: the branch's RL loop.
- Code: `callverse/learning/inference.py`, `simulator.py`, `style_writer.py`;
- benchmarks: `rl_eval`, `policy_eval`, `persona_scale_eval`, `train_style`, `compare_satisfaction`,
  `evaluate_style_candidate`;
- script: `scripts/run_rl_demo.py`;
- tests: `tests/test_rl_pipeline.py`, `tests/test_agent_f_style_training.py`.

Why: 4 of the modules do not import against main (`EpsilonGreedy`, `GaussianThompson`, `LinUCB`, `group_key` are not
in main's `style_policy`). The 2 test files fail against main (`Unsupported reply style: 'apology_first'`). The other
modules depend on those, or on the simulator's data.

Kept: `docs/agent_f.md` and `docs/agent_f_style_reward.md`, each with a note at the top that the code stays on the
branch. Also kept: `benchmarks/agent_f/results/*.json`, `tasks/RL3_report.md`, and the `.gitignore` line
`data/simulated/`.

**Step 2, new login.** 3 conflicts, solved by keeping both sides:
- `webui/api/app.py`: the T27 owner and scan routes (Promotions, Hotel deals, Check now) **and** Dali's Manage routes;
  the import list has both `manage` and `owner`.
- `App.jsx`: Dali's `AppRoutes` (sign-in pages and chooser) plus main's `/admin/promotions` and `/atlas/admin/deals`.
- `Shell.jsx`: the ShopNova admin menu has Refund approvals · Promotions · Dashboard · Manage.

**Step 3, client simulator.**
- `git checkout origin/feature/client-simulator-with-real-data -- client_simulator` (source commit 0d3f65a). This
  includes Mahmoud's committed scorer `client_simulator/models/scorer/scorer_int8.onnx` (34 MB, already in git on his
  branch).
- Adapter `scripts/run_client_simulator.py`. `center_reply()` is the only link: it calls `web_chat.send`.
- The role cards were written for Mahmoud's platform. `CASES` maps the 3 cards used to real scripted cases:
  - SN-01 → order 4512, user 1;
  - SN-03 → order 4514, user 5;
  - AT-02 → booking 7004, user 5 (the card's `BK-7732` does not exist here).
- `requirements-simulator.txt` (new): `onnxruntime==1.31.0` for the scorer, `pyspellchecker==0.9.1` for the typo
  noise.
- Its 24 tests run in the suite. The 2 live tests are skipped unless `CALLVERSE_LIVE=1`.

**Step 4, vision.** 3 conflicts:
- `.gitignore`: both sides kept.
- `README.md`: both sides kept.
- `callverse/pipeline.py` `ticket_note`: the P20 stock warning **and** the photo note.

Every other T28/T30 change in `pipeline.py` merged by itself: Agent C, `continue_agent`, the T30 style policy.

Added in this task:
- `vision.model.available()`: true only if `vision.enabled` is true and torch, transformers, peft, accelerate and
  torchvision import (or a test fake is set).
- In `web_chat`: without those packages, a photo is marked not checked. A photo with no text gets the new fixed reply
  `PHOTO_UNAVAILABLE_REPLY` ("The photo check is not available right now…").
- New `tests/test_t34_vision_guard.py` (2 tests, no model).
- One vision test now has short parameter ids. The long ids (megabytes of `x`) broke pytest on Windows: "the
  environment variable is longer than 32767 characters".

**PC environment.** With Yassine's OK (2 Nov), `.venv` torch went from `2.14.1+cpu` to `2.14.1+cu130`. Also
installed: `torchvision 0.29.1+cu130`, `peft 0.21.2`, `accelerate 1.15.0`, `bitsandbytes 0.50.2`, `onnxruntime`,
`pyspellchecker`.
- Before / after package lists: `out/t34_pip_freeze_before.txt`, `out/t34_pip_freeze_after.txt`.
- `pip check`: no broken requirements.
- Core `requirements.txt` is unchanged (still the CPU torch).
- M3 and M4 still force `device="cpu"`.

**New scripts**
- `scripts/run_client_simulator.py`: 3 simulated clients through the center.
- `scripts/t34_photo_check.py`: 3 real photos through the Help chat door.

**Docs**
- README: T34 line (what came in, from which branch, how to install the optional parts).
- `docs/DEMO_RUNBOOK.md`: "Optional flows" (the photo step, the simulator command).

## 3. Evidence
- **Tests:**
  - After step 1: 1879/1879.
  - After step 2: 1907/1907 (+28 from Dali's API tests); vitest 77/77; `npm run build` OK.
  - Sign-in pages: `vite preview` answers HTTP 200 on `/shop/login`, `/atlas/login`, `/console/login` and `/login`.
    The Portals vitest file renders each page.
  - After step 4: **2003 passed, 5 skipped**. The skips: 2 simulator live tests (need `CALLVERSE_LIVE=1`),
    `test_web_api` and `test_web_speech` (no `av` package: the voice extras are not installed), and
    `test_web_browser` (needs `RUN_BROWSER_TESTS=1`). The same suite run again at the end: 2003 passed, 5 skipped.
- **Vision memory check** (`out/t34_vision_memcheck.txt`): `quant nf4`, `device cuda:0`.
  - torch peak 1662 MiB, VRAM used 2205 MiB, process RAM 1875 MiB.
  - First photo 21.7 s (includes the model load); then about 4 s per photo.
  - The very first run downloaded the model (about 4.5 GB), so it took 27 min.
- **Real photos** (dataset photos; sha256 checked against `benchmarks/vision_qlora/manifest.jsonl`; messages written
  for this check). `python -m scripts.t34_photo_check`, output `out/t34_photo_check.json`. Run twice, same results:

  | # | Photo | Photo check (qlora) | Outcome | Written |
  |---|---|---|---|---|
  | P1 | ShopNova, cracked phone (cv001) | cracked_screen, damage yes → proof yes | **escalate** (colleague), 49 s | nothing |
  | P2 | ShopNova, intact phone (cv025) | no_visible_issue → not proof | **escalate** (colleague), 29 s | nothing |
  | P3 | Atlas, damaged suitcase (cv057) | damaged_room_fixture (wrong label, damage yes) | decline (refund rules for 7004), 25 s | nothing |

  Why P1 escalated:
  - Agent B (`callverse-m2-v3`) got the note "[Photo check … visible damage = True … Photo proof for R-DMG-01 = yes]".
  - It still answered "Please send a photo of the damage" and proposed nothing.
  - The vision path in `final_reply` never asks again for a photo that was already sent, so it passed the case to a
    colleague.
- **Simulator** (`out/t34_simulator.md` / `.json`, trace `traces/run_20261102_212459_426602.jsonl`): 3/3
  conversations ran end to end, 0 crashes.
  - Each one ended after the client's first message, because the center's answer set the ticket to Solved (info).
  - Writer gemma3:1b: 0.4–3.6 s per message. Center: 9.5–15.1 s.
  - Scores: SN-01 1/5, SN-03 1/5, AT-02 1/5. The clients were angry and the answers gave status only.
- **72-message regression** (`out/t34_run72.sh`, `out/t34_compare.txt`, compared with T30's runs):
  - Results: **72/72**, wrong writes 0, crashes 0, leaks 0, API calls 0.
  - Time: avg 19.0 s, max 25.7 s.
  - No message changed result.
  - No photo was sent, so vision was not used.
- **Memory with everything loaded** (`out/t34_memory_peak.json`; Ollama `callverse-m2-v3` 3.9 GB + `qwen2.5:1.5b`
  1.2 GB, Intake models, vision nf4; sampled during the photo run):
  - RAM: 6282 → **7876 of 7885 MiB**.
  - VRAM: 5163 → **5890 of 6141 MiB**.
- **Data:** `shopnova.db`, `atlas.db` and `callverse.db` were saved to `out/t34_dbbackup/` and put back after every
  run (`cmp` identical). The simulator and photo runs use their own tickets files.
- **Checks:**
  - `tests/data/*` is unchanged. The locked sets were only run in the regression, as the task says.
  - Nothing under the root `models/` or `data/raw/` is in git. No secrets; `.env` was not read.

## 4. Problems
- **The PC is at its memory limit when vision is used.** RAM is full (Windows starts swapping), and only about
  250 MiB of VRAM is left. The photo run still finished and gave the same results. But a live demo with the photo
  check, both Ollama models, the web UI and a browser is fragile.
- **Agent B ignores the photo proof** (P1). With damage proven by the photo, B still asks for a photo, so a valid
  damage case goes to a colleague instead of a refund. This is safe (nothing is paid), but the photo then adds nothing
  to the demo story. Agent prompts are locked, so I changed nothing.
- **The photo label can be wrong** (P3: a suitcase was labelled `damaged_room_fixture`). It did not matter here: at
  Atlas the text decides the reason, and the photo is only a note.
- **Simulator conversations are one turn.** The center solves "info" answers at once, so the client never writes a
  second message. All 3 scores are 1/5.
- **The `.venv` now has CUDA torch** (about 2.5 GB more on disk). Teammates' setups are not affected, because
  `requirements.txt` still installs the CPU build. To go back:
  `pip install torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu --force-reinstall --no-deps`.
- **The vision merge also brought Molka's voice + text website** (`callverse/web`, `scripts/run_web.py`, a `voice:`
  block in `config.yaml`, `requirements-voice.txt`). It is a separate app on port 8080, used only when started. Its
  README text says "REAL mode = Agent A", which is older than the current flow. Not checked live in this task (the
  voice extras are not installed).
- **The agent F RL work is not usable from main** until it is ported to the T30 style names and policy.

## 5. Questions for the Brain
1. **Agent B and photo proof.** Should a damage case whose photo shows damage reach the refund path? Options:
   - a code rule: when `proof_received` is true and B answers only "send a photo", the pipeline re-runs B once with a
     note (like `c_offer_retry`);
   - a prompt change for B (prompts are locked: needs your OK);
   - keep it as is: the photo case goes to a colleague.
2. **Vision in the live demo?** Memory is at the limit (section 3). Options:
   - show the photo flow only with the other apps closed;
   - show it as a recorded clip;
   - turn `vision.enabled` off for the demo.
3. **Agent F RL code:** should Semah port it to main's T30 style names and `style_policy` (his lane), or leave it on
   his branch as research?
4. **Molka's voice website** (came with the vision branch): keep it in main as is, or update its "Agent A only"
   text first?
5. **Simulator:** should the next step make conversations longer (for example, a client who replies to an "info"
   answer), so the scores mean something?
6. **Merge into main** needs the OK of Yassine and each branch owner (CLAUDE.md rule 1):
   - **Semah**: `feature/agent-f-rlhf-e2e`, and the vision adapter in `claude/magical-albattani-ktcgao`;
   - **Dali**: `new-login`;
   - **Mahmoud**: `feature/client-simulator-with-real-data` (copied folder);
   - **Molka**: the vision channel and the voice website in `claude/magical-albattani-ktcgao`.

## 6. Next step
Brain review. Then the owners above give their OK, and Yassine merges `feat/t34-integrate` into main. Before the
demo, decide question 2 (vision in the demo).

Merge line for Yassine (after the Brain's review and the owners' OK): `git checkout main && git merge --no-ff origin/feat/t34-integrate`
