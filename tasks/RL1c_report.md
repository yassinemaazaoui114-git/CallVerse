# RL1c report — rating sheet cleanup

Branch `feature/rl1-styles` (not merged). Local SLM only (qwen2.5:1.5b via Ollama), **0 Groq / API calls**. Time box: 45 min, within.

## 1. In plain words
The rating sheet now has 27 situations: h08, a07 and p08 are removed. The bug that left the client's word "team," after the
greeting ("Dear customer, team, …") is fixed: such a leftover word is removed, so the model's text starts with a real sentence.
An empathy sentence that copies the example from the instructions word for word now fails the check (retry, then template).
When two styles wrote exactly the same reply, the row shows only the two different replies, and a new column `n_replies` says how many.

## 2. Done
- `callverse/slm/writer.py`: `LEFTOVER_VOCATIVE_RE` + `drop_leftover_vocative()` (styled path only): removes "team,", "guys,",
  "sir,", "Hello team,", "Dear team,", "ShopNova team," … at the start of the body and of each sentence. "Unfortunately,", "Sure,"
  are untouched (explicit word list, not "any word + comma"). Default writer path unchanged.
- `callverse/slm/reply_styles.py`: `EMPATHY_EXAMPLE` constant (the prompt uses it; prompt text is identical);
  `empathy_problems()` fails a sentence that contains the example word for word.
- `scripts/make_rl1_rating_sheet.py`: 27 fixed situations; `letters_for()` gives one letter per distinct reply; key format
  `{"A": ["short"], "B": ["warm", "warm_next_step"]}`; CSV column `n_replies` (reply_C empty when 2); stats `rows`, `rows_with_2_replies`.
- `tests/test_reply_styles.py`: +28 tests (vocatives "team," / "guys," / "sir," / "Hello team," / "Dear team," / "ShopNova team," /
  "Dear customer, team," × 3 styles; normal first sentence untouched; s02 shape; example copy → retry → template; sheet letters).
  One old test changed: it accepted the example sentence as a good empathy sentence (now rejected on purpose).
- `README.md` RL1 line updated. `check.py`, Coordinator, `callverse/quality/` untouched. Locked test set not opened.

## 3. Evidence
- Tests: **1508 / 1508 passed** (full suite, 190 s). `tests/test_reply_styles.py` 211 / 211.
- Sheet (seed 2026, same files in `out/`: `rl1_rating_sheet.csv`, `rl1_rating_key.json`, `rl1_samples.json`, `rl1_stats.json`):
  **27 rows, 81 replies, 4 rows with 2 replies** (a06, s01, s03, h04: `warm` = `warm_next_step`, outcomes with no closing line).
  h09 was identical in RL1b; now its two warm replies differ.

| style | pass 1st try | after retry | template | avg words | SLM empathy sentence |
|---|---|---|---|---|---|
| short | 100 % | 0 % | 0 % | 18.2 | – |
| warm | 25.9 % | 11.1 % | 63.0 % | 24.4 | 37.0 % |
| warm_next_step | 29.6 % | 14.8 % | 55.6 % | 34.5 | 44.4 % |

- Template ids — warm (17): p01 p02 p04 p05 p10 a01 a02 a03 a04 a06 s02 s03 h01 h02 h05 h06 h11;
  warm_next_step (15): p02 p04 p05 p10 a01 a02 a03 a04 a06 s03 h01 h02 h05 h06 h11; short: none.
- s02's three replies:
  - short (SLM): "Dear customer, please send us a photo of the damage."
  - warm (template, the model copied the example → rejected): "Dear customer, please accept our apologies for the trouble. Please send us a photo of the damage."
  - warm_next_step (SLM): "Dear customer, I'm sorry for the delay. Please send us a photo of the damage."
- Scan of all 81 replies: 0 with a leftover vocative after the greeting, 0 with the prompt's example sentence.

## 4. Problems
- s02 warm_next_step: "I'm sorry for the delay." passes the check but the client's problem is **damage**, not delay. The code
  cannot judge "about the right problem" (same limit as RL1b).
- Warm template share went up slightly (57 % → 63 %): s02 now falls back (wanted). The 1.5b model is still weak at the empathy sentence.

## 5. Questions for the Brain
1. Keep s02 as is (warm_next_step says "delay" for a damaged parcel), or drop / hand-mark it before the team rates?
2. The sheet is ready to send to the team: OK?

## 6. Next step
Brain checks the sheet (`out/rl1_rating_sheet.csv`), then the team rates it. Back to T14d items 5–6 (live) on Monday.
