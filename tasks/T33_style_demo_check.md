# T33 — Style policy demo check: switch ON vs OFF on demo replies, then Yassine decides

## Why
T30 built the style policy; T31 cleaned the real ratings (483 rows, 6 raters). On real ratings the team prefers
`warm_next_step` in 11 of 13 groups (T30 report section 7). The switch is still OFF. Before the demo, Yassine wants to
SEE what the policy changes and then decide ON or OFF. Approved by Yassine on 2 Nov (17:48, decision card).

## Hard limits
- Branch `feat/t33-style-demo` (the Brain created it from main d020ccd; continue on it). Claude Code never merges into
  main. No secrets; never read `.env`. No force push.
- **Do NOT change `config.yaml`** (the switch stays `false`). Turn the policy on only inside the check script
  (patch the loaded config in memory, as `out/t30_spot_on.py` did).
- Policy = the one trained on REAL ratings, `out/rl5_policy.json` (T31). Not the synthetic one.
- Local models only (0 Groq tokens). No change in `callverse/`. Do not open `tests/data/*` (locked sets).
- DBs: back up `shopnova.db`, `atlas.db` and `callverse.db` first; put them back after the run (`cmp` identical).

## What to do
0. Write `tasks/T33_progress.md`, set NEXT.md IN PROGRESS (WIP protocol).
1. `scripts/style_demo_check.py` (new, simple, commented): take **5 demo messages** from the demo stories
   (`scripts/run_demo.py` / the demo screen; mix: ShopNova status, ShopNova decline, an angry client, Atlas decline,
   Atlas ask). For each: run the pipeline once with the policy OFF and once ON (same message, same seed, DBs reset
   between). Print and save `out/t33_style_demo.md`: message, group, chosen style, reply OFF, reply ON, and
   "decision unchanged: yes/no" (compare every decision key except `reply_style`).
2. Checks: 5/5 decisions unchanged, 0 wrong writes, 0 leaks, reply time ON vs OFF (avg seconds).
3. Full suite green (>= 1879). Report `tasks/T33_report.md` (CLAUDE.md format) with the 5 side-by-side replies in the
   report itself (Yassine reads them there), NEXT.md WAITING FOR REVIEW, push.
4. Do NOT turn the switch on. The report's question for the Brain: "ON or OFF for the demo?" with the evidence.

## Time box
30 minutes. Commit a WIP after each step. The report lists the merge line for Yassine (the Brain reviews first).
