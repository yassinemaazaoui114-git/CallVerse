# Finding: what the held-out check showed about Agent C

Written in T32 (2 Nov 2026), from the single held-out run of T31 (`tasks/T31_report.md`, `out/t31_heldout_cd.json`).

## The check
We kept 10 test cases for Agent C (urgent and special help) and Agent D (stock) hidden while the system was built.
They were written by the Brain, not by the person who built the agents. We ran them **once**, at the end, with the
model used in the demo (`callverse-m2-v3`). Nothing was changed after the run, so the score is honest.

| Agent | Practice cases (dev) | Hidden cases (held-out) |
|---|---|---|
| C (language model) | 5/7 | 3/7 (4/7 on a lenient reading of C12) |
| D (fixed rules) | 4/4 | 3/3 |
| C + D | 9/11 | **6/10** official (7/10 lenient) |

## What went wrong (all Agent C, all the model)
1. **C proposes an action when the facts say "no".**
   - C09: the client asks for a new pair of earbuds. The order is **not late** (it is due tomorrow). C read the order,
     wrote "late by 0 days", and still proposed a replacement.
   - C14: the client asks for a replacement watch. The stock is **0**. C asked Agent D, got the answer, and still
     proposed a replacement.
   - C12: the client asks for a 10-day hold (the rule allows 3). C proposed a 3-day hold. This is legal, but the test
     expected no hold at all (the expectation was too strict; see the T31 report note).
2. **C leaves the order number empty when it passes a client to a colleague** (C11, and dev case C06). The hand-over
   itself is right; a detail is missing.

## Why nothing bad happened
In CallVerse, **agents never act directly** (a locked design decision). An agent can only make a **proposal**. The
**Coordinator** is plain code with rules, not a model. It re-reads the real data and checks the rule before anything
is written.
- C09 and C14: the Coordinator sent the proposal back twice, then passed the case to a colleague. Nothing was written.
- C12: a 3-day hold is inside the rule, so the Coordinator asks the client first. Nothing happens without their "yes".
- **0 wrong writes.**

This is the reason the design separates "the model suggests" from "the rules decide". A language model can be fluent
and still wrong, so the model is never the last step before the database.

## Why the practice score looked better
The practice cases had no case where the facts clearly say "no" to Agent C. On practice data C failed only on
details (missing arguments). The hidden cases tested something the practice cases did not, and they found it. This is
why a held-out set is kept apart (CLAUDE.md rule 2).

## Possible fixes (for later, NOT done)
- A small **code pre-check** before C's proposal, like the T29 "no later flight" check for Atlas: refuse
  `propose_replacement` when the order is not late or when D says the stock is 0.
- **More practice cases** of the "facts say no" kind.
- A **model change** for Agent C in `config.yaml`.

Each of these needs a **new** held-out set to measure it. The current one is spent: running it again after a fix
would be tuning on test data.
