# RL1b — Make the 3 reply styles really differ + rebuild the rating sheet

## Why
RL1 (branch `feature/rl1-styles`, not merged) works (1398 tests, default unchanged, 90/90 pass first try), but the Brain read all 90 replies:
the styles were base / base + "I'm sorry for the trouble." / same + one generic line; in 12/30 rows the two apology styles were identical.
The team would only rate "apology yes/no". Greetings were random ("Hi,", "Hello,", none). h03 and h12 carry wrong decisions (T14d bugs).
Approved by Yassine 1 Nov 19:46 (all ⭐: Q1a, Q2, Q3, Q4). Offline: local SLM only, **0 Groq**, no merge.

## Hard limits
Same as RL1: never read `.env`; no secrets; never commit `models/` / `data/raw/`; no force push / rebase / reset; **no merge into main**.
Decisions, amounts, rules, must_say, `check.py`, the Coordinator: unchanged. **Default (no reply style) stays byte-identical to main.**
Do not open `tests/data/t14d_heldout_messages.json`.

## What to do
0. You start on `feat/t14d-request-match` with `tasks/NEXT.md` changed and this file new (written by the Brain). Commit both there
   ("NEXT: RL1b (Brain)"), push. Then `git checkout feature/rl1-styles`, `git pull`.
1. **New style names and meaning** (replace the RL1 names everywhere: code, tests, config, README, `docs/RL_interface_spec.md` styles line):
   - `short`: greeting + the decision (must_say + next step) only. No apology, no empathy, no closing.
   - `warm`: greeting + **one empathy sentence written by the SLM about the user's own problem** + the decision. The empathy sentence has
     **no facts, no numbers, no promises, no dates** (it may name the problem in plain words: "Waiting for a parcel that does not come is
     stressful."). It comes from the user's message (already in the prompt "for tone only"). The rule check applies to the whole reply;
     if the empathy sentence breaks it → normal retry → template (template `warm` = greeting + the fixed calm opener + decision).
   - `warm_next_step`: `warm` + **one closing line by code, by outcome**, from this approved list (exact text):
     | outcome / action | closing line |
     |---|---|
     | approve, refund | If the money does not arrive, reply here and we will check it. |
     | approve, cancellation (cancel_order / booking cancelled) | If you need anything else for this order, reply here. (Atlas: "...for this booking, reply here.") |
     | decline | If you think something is wrong, reply here with the details and we will check it. |
     | info (status) | We will message you here if anything changes. |
     | ask_user, ask_proof, layer3_pending, send_back | no closing line (the request / "we will reply" is already last) |
     Remove the RL1 generic line "You can reply here if you have a question.". If an outcome is not in the table → no line, and list it in the report.
2. **Greeting by code, same for all 3 styles** (Q3): "Dear customer," for a formal user, else "Hello,". The model never writes its own greeting
   when a style is set (strip it like the T05b opener code does). No style set = old behaviour.
3. Prompt: tell the SLM, per style, exactly what to write (short: nothing extra; warm/warm_next_step: one empathy sentence first, then the decision).
   Pinned fingerprints: only the new style prompts may be new; default prompts unchanged.
4. **Tests:** greeting identical across styles; `short` has no apology/empathy; `warm` has exactly one extra sentence before the decision
   (fake SLM); empathy sentence with a number or a promise word → check fails → retry/template; closing line per outcome matches the table
   exactly; must_say identical across styles; default byte-identical (keep RL1's hash test).
5. **Rebuild the rating sheet** (Q4): same 30 situations as RL1 **minus h03 and h12, plus p04 and p06**. Same files and format
   (`out/rl1_rating_sheet.csv`, `out/rl1_rating_key.json` seed 2026, `out/rl1_samples.json`, `out/rl1_stats.json`); overwrite the RL1 ones.
   Add one check line: number of rows where any two styles are identical (target 0).
6. Report numbers per style: pass 1st try / retry / template, avg words, % with empathy sentence, seconds/reply; list every template fallback id.
7. Commit, push `feature/rl1-styles`. **No merge.** Write `tasks/RL1b_report.md`, copy to `out/RL1b_report.md`.
   Then `git checkout feat/t14d-request-match`, put `tasks/NEXT.md` back to T14d IN PROGRESS (items 5–6 Monday), "Last done" = RL1b. Commit, push.

## Checks the Brain will look at
All 90 replies (read before the team gets the sheet): the styles differ in every row; empathy sentences are safe (no facts/promises) and
about the user's real problem; closings exactly as the table; no h03/h12.

## Time box
2 h. WIP stop allowed. Stop if Ollama is down or RAM < 300 MB.
Report format: In plain words · Numbers · Problems · Questions for the Brain · Next step.
