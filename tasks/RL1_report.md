# RL1 report — style-aware reply writer + rating sheet

## In plain words
The writer can now say the same approved decision in three ways: `short` (no apology, just the decision and next step),
`apology_first` (a fixed apology sentence first, then the content) and `apology_next_step` (apology first, then the content, then a
closing next-step sentence). The apology and the closing sentence are written by code, so they are always exact; the small model only
writes the middle. Facts, amounts, rules, `must_say` and the rule check are untouched. With no style set, the writer behaves exactly as
on main. I also built the rating sheet for the team: 30 real situations, each answered in the 3 styles by the local model, with the
letters shuffled and the key kept in a separate file. 0 Groq / API calls.

## Done
- `callverse/slm/reply_styles.py` (new): the style table, `of(decision)` (decision key > env `CALLVERSE_REPLY_STYLE` > `config.yaml`
  `slm.reply_style`; unknown name = error), `closing_for`, `put_last`. One fixed closing line, proposed by me:
  **"You can reply here if you have a question."** (used when there is no `next_step`; for `ask_user` / `ask_proof` the closing is the
  request itself, e.g. "Please send us a photo of the damage."). It passes the rule check for all test decisions.
- `callverse/slm/templates.py`: `decision_opener` follows the style (`short` = never, the two apology styles = always, even for a calm
  client; none = old rule); `render` has a template per style (`short` = greeting + must_say + next step, and "Regarding booking N."
  if Atlas's number is not in the sentences; `apology_next_step` = next step moved to the end / fixed line).
- `callverse/slm/writer.py`: `style_guide(..., reply_style)`, prompt for a closing style (the model is not shown the next step and is
  told it is added after), `add_closing` in `finish`. The off-topic redirect ignores the style.
- `callverse/learning/situation.py` (+ `__init__.py`): `situation(ticket, decision)`, exactly the 9 RL spec fields. Pure; not called by the pipeline.
- `config.yaml`: `slm.reply_style: null`. README updated.
- `scripts/make_rl1_rating_sheet.py` (the only file of the sheet that is committed).
- `tests/test_reply_styles.py`: 101 tests.

## Evidence
- Tests: **1398 passed / 1398** (1297 before + 101 new). Pinned fingerprints (`test_routing_by_company.py`, `test_t14b.py`) unchanged.
  Default output pinned: `build_messages`, `render` and `polish` for 10 decisions x 3 client styles hash identically on main (eeece27) and on the branch.
- Rating sheet: `out/rl1_rating_sheet.csv` (30 rows, 16 ShopNova + 14 Atlas), `out/rl1_rating_key.json` (seed 2026), `out/rl1_samples.json` (90 replies),
  `out/rl1_stats.json`, log `out/rl1_run.log`. All git-ignored.
- Situation ids (all real tweets from the T14b/T14c practice sets and the spent T14c held-out set, used as dev here):
  p01 p02 p03 p05 p08 p09 p10 · a01–a07 · s01–s05 · h01–h09 h11 h12. Left out: the 2 off-topic redirects (p11, p12; fixed text) and 4 more
  dropped by the rule "drop from the most common kind of decision" (p04, p06, p07, h10). Decisions and Intake styles come from the traces
  of the earlier runs (Coordinator output, no agents, no Groq). Outcomes: info, approve, decline (both companies), ask_proof, ask_user, layer3_pending.
- Per style (30 replies each, qwen2.5:1.5b local, temperature 0):

| Style | check pass 1st try | after retry | template | avg words (max) | with apology | seconds / reply |
|---|---|---|---|---|---|---|
| short | 100% | 0% | 0% | 17.3 (36) | 0% | 2.5 |
| apology_first | 100% | 0% | 0% | 22.3 (41) | 100% | 2.5 |
| apology_next_step | 100% | 0% | 0% | 27.7 (42) | 100% | 2.5 |

  `short` stays under 45 words in all 30. The rule check was not changed and no style made it fail.

## Problems
- **The styles differ less than hoped.** In **12 of 30** situations `apology_first` and `apology_next_step` are word-for-word identical
  (ids: p05 a02 a03 a06 s01 s02 s03 h02 h04 h07 h09 h11): the decision already ends with its next step or request, so the closing adds nothing. In the other
  18 the closing is the fixed line "You can reply here if you have a question." — real but generic, and it is the same line every time.
  `short` differs from the others in all 30. Many replies are the Coordinator's sentences nearly verbatim (the model has little room: `must_say` is copied word for word).
  Risk for RL: a bandit may see little difference between the two apology styles.
- The apology styles override Intake's `length` (always "3 to 5 sentences"); `short` too. Intake's length is unused when a style is set.
- Because all 90 passed on the first try, the retry and template paths were tested only with the fake SLM, not with the real one.
- `tasks/NEXT.md` on `main` still says T14d (as before); the RL1 status is in the T14d branch's copy, which I restore as asked.

## Questions for the Brain
1. Keep `apology_next_step` as is, or make it different when the next step is already last (for example a second sentence from a small list of fixed, approved lines, or a different fixed closing per outcome)?
2. Is the fixed closing line OK for the team to rate, or do you want another wording?
3. Short replies: should a greeting ("Hello,") be forced by code? Today the model decides (some replies start without one).

## Next step
Brain reads all 90 replies (`out/rl1_samples.json`) before the sheet goes to the team; decide question 1; then review/merge `feature/rl1-styles` (Yassine runs the merge), then RL5.
