# RL1b report — styles that really differ + new rating sheet

Branch `feature/rl1-styles` (not merged). Local SLM only (qwen2.5:1.5b via Ollama), **0 Groq / API calls**.
Time box (2 h) used; stopped after the third sheet run.

## 1. In plain words
The three reply styles are now `short`, `warm` and `warm_next_step`, and they differ in every situation that has a closing line.
`short` is the greeting plus the decision, nothing else (30/30 first try). `warm` adds one sentence about how the client feels,
written by the small model and checked by code (no number, no date, no promise, no decision); when that sentence fails twice,
the fixed template adds "I'm sorry for the trouble." instead. `warm_next_step` is `warm` plus one closing line from the approved
table. The greeting is the same in all three styles ("Dear customer," for a formal client, else "Hello,"). The main weakness:
the 1.5b model often does not write a usable empathy sentence, so about half of the warm replies use the template sentence.

## 2. Done
- `callverse/slm/reply_styles.py`: new names `short` / `warm` / `warm_next_step`; RL1 names and the generic line
  "You can reply here if you have a question." removed. `greeting()` (Q3), `closing_line()` (approved table, exact texts),
  `empathy_problems()` (the empathy sentence check), the style prompts.
- `callverse/slm/writer.py`: a separate path for styled replies (`styled_guide`, `finish_styled`, `styled_problems`); the
  default path is `main`'s code again (byte-identical). `finish_styled` only deletes or moves the model's sentences:
  model greeting removed (also "Hello there"), ONE feeling sentence moved first (the model often writes it after the
  decision), filler / copied client words / invented sentences removed (a sentence is kept only if it has a must_say
  sentence or ≥ 3/4 of its words come from the decision). Style problems join the rule check → normal retry → template.
  `check.py` and the Coordinator are unchanged.
- `callverse/slm/templates.py`: `render_styled` = greeting + [warm: fixed calm opener] + decision + [closing line].
  `decision_opener` back to `main`'s rule.
- `scripts/make_rl1_rating_sheet.py`: fixed list of 30 situations (RL1's 30 − h03, h12 + p04, p06); the client's message is
  passed as history (tone only); new stats (empathy share, template ids, rows with two identical styles).
- `tests/test_reply_styles.py` rewritten (183 tests): greeting identical across styles, short has no apology/empathy, warm has
  exactly one extra sentence before the decision, bad empathy (number, promise, decision, date, "the client", thank-you) →
  retry → template, closing line per outcome = table, must_say identical, RL1's default hash test kept and passing.
- `config.yaml` comment, `README.md`, `docs/RL_interface_spec.md` (styles line, example, baselines) updated.

## 3. Evidence
- Tests: **1480 / 1480 passed** (full suite, 136 s). Default prompts/templates: RL1's pinned digests (computed on `main`) unchanged.
- Sheet (third run, `out/rl1_stats.json`, 90 replies, 0 API calls):

| style | pass 1st try | after retry | template | avg words | SLM empathy sentence | s / reply |
|---|---|---|---|---|---|---|
| short | 100 % | 0 % | 0 % | 18.0 | – | 2.56 |
| warm | 30 % | 13 % | 57 % | 24.6 | 43 % | 4.43 |
| warm_next_step | 37 % | 20 % | 43 % | 35.7 | 57 % | 4.21 |

- Template fallback ids — warm (17): p01 p02 p04 p05 p10 a01 a02 a03 a04 a06 a07 s03 h01 h02 h05 h06 h11;
  warm_next_step (13): p02 p04 a01 a02 a03 a04 a06 s03 h01 h02 h05 h06 h11.
- **Rows where two styles are identical: 5** (target 0): a06, s01, s03, h04, h09 — all `warm` = `warm_next_step`, all outcomes
  with no closing line by the table (ask_user, ask_proof, layer3_pending). Temperature 0 → same prompt, same text.
  `short` differs from `warm` in all 30 rows.
- Outcomes not in the closing table: none in the 30 situations (all are approve refund / cancel / cancel_hotel, decline, info
  status, or the four "no line" outcomes).
- Files (overwritten): `out/rl1_rating_sheet.csv`, `out/rl1_rating_key.json` (seed 2026), `out/rl1_samples.json`, `out/rl1_stats.json`.
- Run 1 → run 3: warm template 80 % → 57 % (moving the feeling sentence first, removing "Hello there", and repeating the empathy
  request as the last prompt line; trace: 176 of the run-1 failures were "no empathy sentence at all").

## 4. Problems
- **The 1.5b model is weak at the empathy sentence.** About half of the warm replies fall back to "I'm sorry for the trouble."
  Many SLM ones are generic ("I'm sorry for the inconvenience.").
- **Empathy sentences to read before the team gets the sheet** (they pass the check but are not good):
  h08 "I'm sorry to hear that you're not able to cancel the order." (the order IS cancelled: contradicts the decision);
  s02 warm "team, waiting for a parcel that does not come is stressful." (copies the prompt example; the client's problem is damage;
  "Dear customer, team," also wrong) and s02 warm_next_step "team, I'm sorry for the delay."; a07 warm_next_step "…but I'm afraid
  your request cannot be done." (a decision inside the empathy sentence). The code cannot judge "about the right problem".
- 5 rows have `warm` = `warm_next_step` by design (no closing line for those outcomes).
- In run 1 an invented sentence "Your hotel booking 7008 is also cancelled." passed the rule check because it had the booking
  number. Fixed in the styled path (≥ 3/4 decision words). The **default** writer still has no such filter (unchanged on purpose).
- `callverse/quality/satisfaction.py` (Semah's agent F) still lists `STYLES = ["short", "apology_first", "apology_next_step"]`
  for its stacker features (and `tests/test_satisfaction.py` uses `apology_first`). Not changed: it is Semah's lane.

## 5. Questions for the Brain
1. Empathy quality: accept ~50 % template for the sheet, or (a) a second small SLM call that writes only the empathy sentence,
   (b) try `qwen2.5:3b` for the warm styles, or (c) hand-review / drop the bad rows (h08, s02, a07) before the team rates?
2. The 5 identical rows (no closing line by the table): keep them (raters see two identical replies), drop them from the sheet,
   or give those outcomes a closing line?
3. May Semah's `satisfaction.py` STYLES list be renamed to the new names (his lane), or does he do it?

## 6. Next step
Brain reads the 90 replies (`out/rl1_samples.json`), decides Q1–Q2, then the team rates the sheet. After that: back to T14d
(items 5–6, live, Monday).
