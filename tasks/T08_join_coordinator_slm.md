# T08 — Join the Coordinator and the SLM: every user gets one correct, polite final reply

## Why
T07 made the decisions safe (Coordinator). T05/T05b made the wording safe (SLM with `must_say`, rule check,
templates). They are on two branches and not connected: today the user still sees Agent B's own text
("sent for checking", "the Coordinator"), written **before** the decision. T08 joins them so the demo shows
the real flow: **agent proposes → Coordinator decides → SLM writes the final reply from the decision only.**

## Hard limits
- Only the steps below. Do not touch Intake, the platform write functions, the policies file, or the
  held-out test files (`tests/data/*`). Semah's branches (`feature/voice`, `integration/platform-voice`,
  `feature/multimodal-voice-backup`, PR #1) are **parked for the final version**: do not merge, rebase or change them.
- No new LLM provider, no new library. No secrets in files; never read or stage `.env`.
- Agent text never reaches the user any more. It stays in the trace.
- If Ollama is not running, the pipeline must still answer (SLM template), never crash.

## What to do
0. **Merges (approved).** On `main` (pull first): merge `--no-ff` `origin/feature/coordinator` (T07), then
   `origin/feature/slm` (T05 + T05b).
   - Expected conflicts: `config.yaml` → keep both sides (Coordinator/LLM options + `slm` temperature 0, seed 42,
     `qwen2.5:3b`, forbidden list); `tasks/NEXT_PLATFORM.md` → take the version at the end of this file.
   - Run all tests. If they pass, push `main`. Then create `feature/reply` from it.
1. **Decision → user words (Coordinator).** Replace the agent-facing `NEXT_STEPS` with sentences **written to the
   user**, and add `must_say` for the key fact. Only facts from the data or the policy text; **no timing, no
   payment method** (the data does not contain them). Use these (adapt only the grammar):

   | Outcome | `must_say` | `next_step` (to the user) |
   |---|---|---|
   | approve refund (R-REF-03) | "Your refund of {amount:.2f} TND is approved." | "Your order {id} is now cancelled." |
   | approve refund (R-RET-01 / R-DMG-01) | "Your refund of {amount:.2f} TND is approved." | R-RET-01: "The refund is paid once we receive the returned item." · R-DMG-01: "" (empty is fine) |
   | approve refund after Layer 3 (S4) | "Your refund of {amount:.2f} TND is approved after a check by our finance team." | "Your order {id} is now cancelled." |
   | `layer3_refused` | "We cannot approve a refund of {amount:.2f} TND for order {id}." | "Our finance team reviewed it and did not approve it." |
   | approve subscribe | "You will get a message here when your order is {event in words}." | "" |
   | `ask_user` | "Please confirm that you want a refund of {amount:.2f} TND for order {id}." | "" |
   | `ask_proof` | "Please send us a photo of the damage." | "" |
   | `escalate` | "Your case needs an extra check, so it has been passed on for review." | "" |
   | `info` (no proposal; see step 2) | "Your order {id} is {status in words}." | R-DEL-02 case only: "If you like, we can send you a message when it is out for delivery." |

   `send_back` and `refused` are internal: the user never gets a reply for them (the loop continues or ends in
   another outcome). Put `amount_tnd`, `threshold_tnd` (when Layer 3), `order_status`, `days_late`, `event` in
   `facts` as the SLM's decision format (`docs/decision_format.md`) expects. Status words: a small fixed map in code
   (e.g. `stuck_at_depot` → "delayed at the delivery depot").
2. **`info` decisions for Agent A.** When the agent ends **without** a proposal (status questions), the pipeline
   builds an `info` decision from facts it reads itself with `get_tracking` (not from the agent's text):
   `order_status`, `days_late`, `promised_date`, `carrier` if present.
3. **Final reply = SLM.** In `callverse/pipeline.py`, after the decision, call
   `callverse.slm.writer.write_reply(decision, history)` with `decision["style"]` from the Intake ticket
   (`formality`, `length`, `shouting`, `emotion`, `sentiment`). The pipeline result gets `final_reply`, `reply_source`
   (`slm` / `slm_retry` / `template`) and keeps the agent text as `agent_text` (trace only). Trace step `final_reply`.
4. **Dali's 3 small fixes (code, not prompt)** in `callverse/slm/writer.py`:
   - punctuation/capitals: no ", Your …" (comma + capital) → split into two sentences; every sentence starts with a capital;
   - repeated sentence: a `must_say` sentence appears **once** (drop exact duplicates, case-insensitive);
   - formal greeting by code: `style.formality == "formal"` → reply starts with "Dear customer," (before the calm opener,
     if any). Casual/neutral: no fixed greeting.
5. **T07 follow-ups (approved 2026-10-21).**
   - keep `reasoning_effort: low`;
   - Coordinator trace warning `rule_not_searched` when the cited rule was not returned by `search_policy` in that turn
     (warning only, no refusal);
   - `config.yaml`: simulator model → `gemini-3.5-flash` (3.8 was 47–76 s per call).
6. `scripts/run_scenario.py` prints the final reply (and its source) at the end of S1, S2, S4. Add an `S0` = info case
   ("Hi, where is my order 4510?").

## Checks (with numbers)
- All tests pass (report x/y; the 3 that need the intake models are OK to name if they fail here).
- **S1:** final reply contains "Your refund of 59.90 TND is approved." exactly once; order 4512 → refunded.
- **S2 `--inject-error`:** exactly one final reply, after the approval; it contains 59.90 and **not** 70.
- **S4:** final reply contains "Your refund of 378.00 TND is approved after a check by our finance team."
- **S0:** reply states 4510's status from tracking; no refund wording.
- **Leak check on every final reply of S0, S1, S2, S4:** 0 matches for "coordinator", "agent", "proposal", "P-0",
  "R-" + digits, "sent for checking".
- Angry message ("ORDER 4512 IS A WEEK LATE!!! I WANT MY MONEY BACK") → reply starts with the calm opener.
  A formal message ("Dear ShopNova, … Kind regards") → reply starts with "Dear customer,".
- Same S1 run twice → **identical** final reply text.
- Ollama stopped → S1 still gives a final reply (`reply_source: template`), no crash.
- Seconds per scenario (Groq + SLM), and model used for the SLM (3b or 1.5b).

## Time box and stop rule
2 h 30 min. Stop and report if the merges need more than the expected conflict fixes, or if the leak check fails
after 2 tries.

## Git (approved by Yassine, 2026-10-21)
Step 0 merges into `main` and push (approved; Dali agreed to fold his fixes in). Then commit and push
`feature/reply`. **No other merge.** Write `tasks/T08_report.md`, set `tasks/NEXT.md` to WAITING FOR REVIEW.

---
### `tasks/NEXT_PLATFORM.md` content to use when resolving the conflict in step 0
```
# NEXT PLATFORM TASK (Dali's lane — P tasks)

| Field | Value |
|---|---|
| Status | READY |
| Task file | tasks/P08_sim_clock.md (branch feature/sim-clock from latest main) |
| Approved by | Yassine 2026-10-21 |
| Last done | T05b — accepted by the Brain 2026-10-21 (held-out v2: 6/6, must_say 6/6, 0 forbidden, qwen2.5:3b); merged into main in T08 |

Status values: READY · IN PROGRESS · WAITING FOR REVIEW · DONE
Core tasks (T) are tracked in tasks/NEXT.md — do not touch it.
```
