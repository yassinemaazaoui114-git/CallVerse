# I01 — Integration: platform + Intake + voice channel (Semah's lane, proposed)

> **Status: APPROVED (Git section below), relayed by Semah — see "Approved by".** Built and tested at Semah's request in the local branch
> `integration/platform-voice` (from `main` c2984b1). Published only as this branch + one PR to `main` (not merged).
> `tasks/NEXT.md`, `tasks/NEXT_PLATFORM.md` and the other developers' branches are not touched.

## Why
One CallVerse workflow for text and voice: customer → (Whisper) → Intake → Router → agent → Coordinator →
response → (Piper) → customer, reusing what the team already built, without faking what is not built.

## Contents
- `main` (c2984b1): platform P01–P04 + Intake T03 (reviewed, merged by Yassine in T04a).
- `platform` P05 (`d1dff86..657b44f`): the local platform server + admin dashboard. **Not reviewed yet.**
  It is included so the integration is complete; it stays on 127.0.0.1.
- Voice V01 (from the `feature/multimodal-voice` patch) + the new `callverse/integration/` workflow.
- Report: `tasks/I01_report.md` (187/187 tests on c2984b1; browser end-to-end 2/2, 3 runs).

## Hard limits (respected)
- No change to agents, `llm.py`, tools/registry, Intake, platform files, policies, or other developers' tests.
- Missing components are interfaces only (Agent B, Coordinator, SLM: "not built", fail closed). RAG is out of scope.

## Before publishing: refresh onto the latest `main`
`main` moved to **22aa220** (T04 router merged) after this branch was built. I01 does not apply cleanly on it:
there are conflicts in `config.yaml` (both sides added sections) and `tasks/NEXT_PLATFORM.md`.
The refresh only resolves those conflicts (keep both sides; NEXT_PLATFORM = `main`'s version) and lets the real
T04 router replace `callverse/integration/interim_router.py` (same interface, it is then deleted).
Tests are re-run, and the numbers go in `tasks/I01_report.md`, before any push.

## Git (TO BE APPROVED BY YASSINE)
Scope: **only** the branch `integration/platform-voice` and **one** pull request. Nothing else.
1. In `integration/platform-voice` (created from `main` c2984b1): `git merge origin/main` (22aa220, a merge commit,
   no rebase) and resolve as described above; run all tests; they must all pass.
2. Commit the I01 work on `integration/platform-voice`.
3. `git push -u origin integration/platform-voice` (no force push).
4. Open a pull request `integration/platform-voice` → `main` for review. **Do not merge it.**
Not allowed: any push to `main`, `platform`, `feature/intake`, `feature/pipeline`; any merge into `main`;
deleting or rewriting any branch. `feature/multimodal-voice` (V01) stays as it is.

Approved by: **Yassine — 2026-10-20, relayed by Semah Ayachi** in the Builder session (Semah: "Yassine has
explicitly confirmed to me that he approves the I01 integration work and its Git publication").
This approval was given verbally to Semah; it is **not independently verified** on GitHub or in this repository.
Yassine: please confirm it in the PR review.

Order actually used (same result as steps 1–2 above): first commit the I01 work on c2984b1, then
`git merge origin/main` (merge commit), then replace the interim router and re-run all tests.
