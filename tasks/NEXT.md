# NEXT TASK — Yassine's lane (core)

| Field | Value |
|---|---|
| Status | READY |
| Task file | tasks/T14d_request_action_match.md (a write must match what the user asked: money words are not an order cancellation, Atlas ticket refund needs a money-back request, wrong-write check counts order status, "not refunded yet" = complaint; 12 new held-out real tweets) |
| Approved by | Yassine — 2026-11-01 13:33 (B1 + C1–C3) |
| Model | Sonnet 5.5 (use /model — T14c ran on Opus), new conversation, branch from main after T14c merge. Offline coding now; live runs on Monday's Groq quota |
| Last done | T14c — merged 3672c35 (fast-forward, by Yassine), 1283 tests pass: Atlas declines by code, shared negation check, R-DMG-01 proof flag, damaged item asks photo, off-topic fixed text. Held-out 9/12 (below bar) → T14d |

Next after T14d: RL1 → step 09 → agent C → agent D.

Status values: READY · IN PROGRESS · WAITING FOR REVIEW · DONE
Roadmap (Notion): CallVerse — Full Version Roadmap (finished tasks in its "Done" table) · Dali's lane: tasks/NEXT_PLATFORM.md · Semah's lane: tasks/NEXT_VOICE.md
