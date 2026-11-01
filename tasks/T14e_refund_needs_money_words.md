# T14e — An Atlas refund needs the user's own money-back words (t02) + look at t05 + CLAUDE.md model line

## Why
T14d held-out (10/12, merged ff05d4a): **t02** "cancelled flight … no confirmation from BA to hotel. Help" (booking 7008) got a **690 TND
refund the user never asked for**: Intake found `refund_request` by meaning and `ACTION_REASONS` trusts the reason. **t05** "Cancelled ticket
2 months back and still no refund" got only info. Approved by Yassine 1 Nov 23:46 (all ⭐). The T14d held-out is now **dev material**
(seen); fixes must be general rules, tested on synthetic sentences + all dev sets, not patches for one tweet. No merge.

## Hard limits
Never read `.env`; no secrets; never commit `models/` / `data/raw/`; no force push / rebase / reset; **no merge into main**.
No change to thresholds, rule texts, Intake models, prompts. Runs are local (Dali's model is now the default; 0 Groq expected — report any Groq call).

## What to do
0. `git checkout main`, `git pull` (main = ff05d4a or later; this file and NEXT.md are uncommitted on main: commit them first
   "NEXT: T14e (Brain)", push). Branch `feat/t14e-refund-words`. Full suite first (expect 1350).
1. **Atlas money-back words** (`callverse/intake/request_words.py`, same style as `cancels_order` / `asks_for_expenses`):
   `asks_for_money_back(message)` = whole words/phrases like refund, refunded, money back, my money, pay (me) back, reimburse(ment) of the
   ticket / booking / flight, chargeback. In `atlas_coordinator`: a ticket **refund** (and a hotel refund) is confirmed **only if the message
   asks for money back**; otherwise the user is **asked first** (ask_user: "Do you want a refund of X TND for booking N?"), nothing written.
   Cancellations of a confirmed booking (T21) keep their own path. If ShopNova has the same "refund by meaning only" path, report it
   (do not change ShopNova in this task).
   Tests: ≥ 8 synthetic sentences each way (e.g. "my flight was cancelled, help" → ask; "I want my money back" → refund; "refund me" → refund;
   "no confirmation to the hotel" → ask; "still no refund" → refund request).
2. **t05** ("still no refund" → info): find the cause in the trace (`out/t14d_heldout.json`, its trace) — Intake reason, negation step, or the
   model. Fix only if the cause is a general rule bug (e.g. negation step 1c misses "still no refund"); add synthetic tests. Report the cause either way.
3. **CLAUDE.md** model lines: replace the "M2 Agent B = Groq …; Agent A + Intake fallback = local cv-qwen3.5-4b" lines with:
   "M2 Agents A and B = local `callverse-m2-v3` (Dali's fine-tuned Qwen3-4B, GGUF in git-ignored `models/m2/`, load with
   `ollama create callverse-m2-v3 -f models/m2/Modelfile_v3`); backups: A → `cv-qwen3.5-4b` → `cv-phi4-mini`; B → Groq `openai/gpt-oss-120b`
   → `openai/gpt-oss-20b` → Gemini. Intake LLM fallback = `cv-qwen3.5-4b` (`CALLVERSE_AGENTS_SET=local`)." Nothing else in CLAUDE.md.
4. **Check** (local, app setup): the 60 dev messages (same 5 files + runners as T14d step 2) **plus** `tests/data/t14d_heldout_messages.json`
   (dev now) = 72. Report passes, wrong writes (M2T3 definition), crashes, leaks, Groq calls, and every message whose result changed vs
   `out/t14d_D_*.json` / `out/t14d_heldout.json`. Bar: 0 wrong writes, 0 crashes / leaks, no message that passed before now fails.
5. Full suite green. Commit, push `feat/t14e-refund-words`. **No merge.** Write `tasks/T14e_report.md` (In plain words · Numbers · Problems ·
   Questions for the Brain · Next step), copy to `out/T14e_report.md`, set `tasks/NEXT.md` to WAITING FOR REVIEW. Commit, push.

## Time box
1.5 h (72 local runs ≈ 25 min). WIP stop allowed.
