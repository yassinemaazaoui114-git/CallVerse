# T35b report — Live steps and saved steps for a photo message

Branch `feat/t35b-photo-steps` (from main 01a1836). Not merged. Task: `tasks/T35b_photo_steps.md`.

## 1. In plain words
When a customer sent a photo, the chat showed only "Sending…" until the reply came. The ticket also kept only one
step, so the Console could not show what the center did. The cause was one line: saving the photo check step also
switched off the step recorder, before the rest of the work started. Now the photo step leaves the recorder on. A
photo message shows its live steps and saves all its steps, like a message without a photo. Then (approved by
Yassine) the chat also says "Checking your photo…" right away, so the customer is not left waiting ~30 s with no news.

## 2. Done
- `callverse/channels/web_chat.py`:
  - New `save_heard()`: it saves the steps heard so far and keeps listening.
  - `flush()` = stop listening + `save_heard()`. Its behavior is the same as before.
  - `channel_step(kind, data, keep_listening=False)`: only the `photo_check` step passes `keep_listening=True`. All
    other channel steps (error, quota, approval, identity, …) still stop listening, as before. These steps come at
    the end of a message, and one test (`test_any_error_gives_the_escalate_reply_and_an_error_step`) depends on that.
  - Listening still always ends in `finish()` or in the `finally: flush()` of the listening block, so no listener is
    left behind.
- `tests/test_vision_integration.py`: `test_photo_message_keeps_live_steps_and_saves_the_pipeline_steps`. A photo
  message must give live texts and save `photo_check`, `route` and `coordinator`, in time order, and leave no listener.
  **It fails on the old code** (`assert 0 >= 2`: no live text) and passes with the fix.
- **Add-on (approved by Yassine, 2 Nov: "yes, add 'Checking your photo…'")**: `PHOTO_STEP_TEXT = "Checking your
  photo…"`. The channel says it itself, just before the photo check (no trace line comes before the photo model
  has loaded). It goes through the same shown-once rule (`say()`, now shared with `listen`). It is said only when a
  photo is sent. Tests: it is the first live text of a photo message, and a message without a photo never gets it.
- README (one note under Vision). This report and the task file.

## 3. Evidence
- `python -m pytest -q --ignore=tests/data` → **2005 passed, 5 skipped** (main 2003 + 2 new).
- Live check (2 Nov, 23:46): real models (vision qlora nf4, `callverse-m2-v3`, `qwen2.5:1.5b`), temporary tickets DB.
  I called `web_chat.send` directly: sara, `My order 4509 arrived damaged, see the photo. I want a refund.` + cv001
  (cracked phone).

  | | Before (T35 live, same message) | After (T35b) |
  |---|---|---|
  | Live steps shown | 0 | 5: Reading your message (34.8 s), Checking your order (37.0), Checking with our refund team (39.4), Checking the rules (57.1), Writing the reply (60.2) |
  | Steps saved on the ticket | 1 (`photo_check`) | 22 (`photo_check`, intake, route, llm, tools, search_policy, coordinator, slm…) |
  | Outcome | escalate, nothing written | escalate, nothing written (same) |
  | Listeners left after | — | 0 |

  Time: 64.5 s, including the model load.
- Live check after the add-on (same message, same photo): live texts **Checking your photo… (5.5 s)**, Reading
  your message (32.5), Checking your order (34.9), Checking with our refund team (37.2), Checking the rules (53.1),
  Writing the reply (56.2). Escalate, 22 steps saved, 60.5 s.

## 4. Problems
- The photo model still takes about 25 s to load on the first photo. The customer now sees "Checking your photo…"
  during that time.
- This branch and T35 (`feat/t35-react-photo`) are separate. The React chat shows these steps only after both are
  merged. I placed the README note away from T35's README line, so the two merges should not conflict.

## 5. Questions for the Brain
- None.

## 6. Next step
Merge line for Yassine (after the Brain's review; core code, Dali's OK not needed):
```
git checkout main && git pull && git merge --no-ff origin/feat/t35b-photo-steps && git push
```
Then run the tests on main. Merge T35 (after Dali's OK) before or after this: the order does not matter.
