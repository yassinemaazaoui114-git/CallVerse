# T35b — Live steps and saved steps for a photo message

Approved by Yassine, 2 Nov 2026 ("yes, fix it in T35b"), after T35's report (Problems 1, Question 1).
Task file written by the Builder from that approval (no Brain task file).

## Why
In `callverse/channels/web_chat.py`, the `photo_check` channel step called `flush()`, which stops the step listener.
That step comes BEFORE the pipeline, so a message with a photo showed no live steps (only "Sending…") and its ticket
kept only the `photo_check` step (the Console's "What was done" was almost empty). Found live in T35.

## What to do
- Fix it in `web_chat.py` only, as narrow as possible: the photo step must not stop the listener. Every other
  channel step keeps its current behavior.
- A test that fails on the old code: a photo message gives live steps, saves the pipeline steps after
  `photo_check` in time order, and leaves no listener behind.
- Full suite green; one live check with the real models; README; report.

## Limits
Branch `feat/t35b-photo-steps` from main (separate from the T35 UI branch: core code, no need for Dali's OK).
No change to agents, prompts, Coordinator, vision, config. Never merge into main.

## Add-on
Approved by Yassine, 2 Nov 2026 ("yes, add 'Checking your photo…'"): a live text before the photo check.
