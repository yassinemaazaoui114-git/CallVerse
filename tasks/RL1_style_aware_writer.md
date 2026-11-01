# RL1 — Style-aware reply writer (3 reply styles) + rating sheet for the team

## Why
RL plan (`docs/RL_interface_spec.md` v1.1): a bandit (RL5) will choose HOW the writer says an already-approved decision; the reward is
agent F (+ real ratings). RL1 gives the writer a **reply style** to obey. Approved by Yassine 1 Nov 16:21 (A1 + B3): RL1 now, offline
(local SLM only, **no Groq**); and the team rates replies in the 3 styles (real preference data, B1) → RL1 also builds that rating sheet.
F as merged ignores the reply, so this real data is what will make the reward depend on the style.

## Hard limits
- Never read `.env`; no secrets; never commit `models/` or `data/raw/`; no force push / rebase / reset; **no merge into main**.
- **0 Groq / API calls.** Only the local SLM (Ollama, role `slm`). Start Ollama first; stop if it is not running.
- Decisions, amounts, rules, must_say, the rule check (`check.py`) and the Coordinator are **unchanged**. The style changes wording only.
- **Default = today's behaviour exactly.** With no reply style set, every existing test and every pinned prompt fingerprint must stay the same.
- Do not open `tests/data/t14d_heldout_messages.json` (T14d is not finished).
- Naming: the decision already has `style` (Intake's profile: formality, length, sentiment, shouting). The new field is **`reply_style`**. Do not rename `style`.

## What to do
0. You start on `feat/t14d-request-match` with `tasks/NEXT.md` changed and this file new (written by the Brain). Commit both there
   ("NEXT: RL1 (Brain)"), push. Then `git checkout main`, `git pull`, branch **`feature/rl1-styles`**.
   (This file stays readable with `git show feat/t14d-request-match:tasks/RL1_style_aware_writer.md`.)
1. **Reply styles** (`callverse/slm/reply_styles.py`, one dict, plain words):
   - `short`: no apology, no calm opener; 2–3 sentences, ≤ 45 words; decision + next step only.
   - `apology_first`: the calm opener **by code** first (even if Intake did not flag the user as upset), then the content; 3–5 sentences.
   - `apology_next_step`: calm opener by code + content + a **closing next-step sentence by code** (from `decision["next_step"]` / must_say
     if present; else one fixed closing line you propose and list in the report).
   - `None` (default): today's rule (calm opener only when `is_upset(style)`), unchanged.
   - The off-topic redirect ignores `reply_style` (fixed text, T14c).
2. Writer: `write_reply(decision, ...)` reads `decision.get("reply_style")`; `style_guide()` gets the style's length/apology lines; code parts
   (opener, closing) follow the style. **Template fallback per style** in `templates.py` so a failed SLM reply still matches the style.
   Rule check unchanged; if a style makes the check fail more often, report it (do not loosen the check).
3. **Situation** (`callverse/learning/situation.py`): `situation(ticket, decision) -> dict` with exactly the RL spec fields
   (`company, reason, outcome, action, rule_id, emotion, sentiment, priority, days_late`). Pure function + tests. Not called by the pipeline yet.
4. How a style gets in (for now): `config.yaml` `slm.reply_style: null` and env `CALLVERSE_REPLY_STYLE` (tests / runs). RL5 will set it later.
5. **Tests:** each style on approve / decline / ask_proof / layer3_pending / info for both companies (fake SLM): opener present or absent as the
   style says, closing line present for `apology_next_step`, must_say kept, word limit for `short`, template fallback matches the style;
   default (None) gives byte-identical output to main on the existing writer tests.
6. **Rating sheet (offline, local SLM):** 30 situations from **real** messages we already used (`tests/dev/t14b_practice_messages.json`,
   `tests/dev/t14c_practice_messages.json`, `tests/data/t14c_heldout_messages.json` = dev now; mix both companies and outcomes; list the ids).
   For each: a decision dict built by code from the seeded order/booking facts and the outcome the earlier runs got (`out/t14b_after.json`,
   `out/t14c_practice_run1.json`, `out/t14c_heldout.json`; no agents, no Groq), then the reply in the 3 styles with the real local SLM.
   Write `out/rl1_rating_sheet.csv` (situation_id, company, user message, one-line decision summary, reply A, reply B, reply C — styles **shuffled
   per row with seed 2026**) and `out/rl1_rating_key.json` (which letter = which style; **not** in the sheet). Also `out/rl1_samples.json`
   (all 90 replies with style, check result, SLM or template, word count). These `out/` files are git-ignored; commit only the script
   `scripts/make_rl1_rating_sheet.py`.
7. Report numbers: per style — check pass rate (first try / after retry / template), average words, % with an apology; SLM seconds per reply.
8. Commit, push `feature/rl1-styles`. **No merge.** Write `tasks/RL1_report.md` and copy it to `out/RL1_report.md`.
   Then `git checkout feat/t14d-request-match` and put `tasks/NEXT.md` back exactly to T14d IN PROGRESS (items 5–6 Monday), "Last done" = RL1. Commit, push.

## Checks the Brain will look at
- Default unchanged (existing tests + pinned fingerprints); the 3 styles really differ; facts and must_say identical across styles.
- Rating sheet: 30 rows, real messages only, shuffled letters, key separate. The Brain reads all 90 replies before the sheet goes to the team.

## Time box
2.5 h (most of it is the 90 local SLM replies). WIP stop allowed. Stop and report if Ollama is down or RAM < 300 MB.
Report format: In plain words · Numbers · Problems · Questions for the Brain · Next step.
