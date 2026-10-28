# T13d report — RAG check: top-1 / top-2 / top-3, the agents' real queries, cut rules

## 1. In plain words
When an agent needs a company rule, it types a short search and gets back the 2 rules whose meaning is closest.
On 18 new questions the right rule was among those 2 in 17 cases (top-1 14/18). The one miss was a notification
question that got two delivery rules instead. In the agents' 31 real searches from T12 and T13c, the right rule was
among the 2 in 28. Two of the 3 misses happened on one message ("refund 4512 70 TND"), where the agent searched for
"depot / 6 days late" and got the two delivery rules. The search fails mostly between look-alike delivery rules,
and it cannot say "no rule": a cancellation question gets refund rules with normal-looking scores. Only one rule
(R-REF-05) is cut by the 300-character limit, and it loses only the last 2 words.

## 2. Done
- Branch `feature/t13d-rag-check` from `origin/main` 6a88a4e. First commit bd92dbf: task file, held-out set v2, NEXT.md.
- `scripts/eval_policy_search.py`: now also counts **top-2** (= what the agents see). For each question it prints the
  3 rules with their scores and the **gap** between the 1st and 2nd score. A question with an empty `expected` list is
  printed as `not scored` and left out of the counts. A small `grade()` function gives the mark (OK / top2 / top3 / MISS).
- New offline test `tests/test_eval_policy_search.py` (1 test). A fake search returns fixed rules, so the test
  loads no model. It checks the 4 marks, the counts, the "not scored" case and the gap.
- Ran the new set v2 once and the old T06 set once (local CPU embeddings, 0 API calls).
- Read the existing traces of T12, T13b and T13c (no new agent run) and listed every `policy_search` step.
- No change to `callverse/kb/*`, policies, prompts, agents. Nothing tuned on the held-out set.

## 3. Evidence

### Tests
`.venv/Scripts/python.exe -m pytest -q` → **317 passed** / 317 (66 s), new test included.

### New held-out set v2 (`tests/data/policy_search_questions_v2.json`), output as printed
```
OK         p01: expected ['R-DEL-02']  found [R-DEL-02 0.733  R-RET-01 0.718  R-REF-03 0.701]  gap 0.015  | My parcel was supposed to come 3 days ago and still nothing, can I get money back?
OK         p02: expected ['R-REF-03']  found [R-REF-03 0.771  R-DEL-02 0.721  R-RET-01 0.695]  gap 0.050  | It's been 9 days past the date you promised, I want a full refund
OK         p03: expected ['R-REF-05']  found [R-REF-05 0.733  R-REF-03 0.696  R-ESC-01 0.689]  gap 0.037  | You already refunded part of my order, refund the rest plus 20 TND extra
OK         p04: expected ['R-REF-05']  found [R-REF-05 0.698  R-RET-01 0.689  R-DEL-02 0.686]  gap 0.009  | I chose cash on delivery and the package never came, refund please
OK         p05: expected ['R-RET-01']  found [R-RET-01 0.659  R-DEL-02 0.604  R-DEL-01 0.576]  gap 0.055  | Got the shoes last week, never worn, still in the box, can I send them back?
OK         p06: expected ['R-RET-01']  found [R-RET-01 0.717  R-DMG-01 0.638  R-REF-03 0.628]  gap 0.079  | I received my blender a month ago and want to return it
OK         p07: expected ['R-DMG-01']  found [R-DMG-01 0.626  R-RET-01 0.490  R-REF-03 0.489]  gap 0.136  | The screen of the tablet I received is cracked
OK         p08: expected ['R-DMG-01']  found [R-DMG-01 0.633  R-DEL-02 0.517  R-RET-01 0.512]  gap 0.116  | Box arrived crushed and the mug inside is broken, I want a new one
OK         p09: expected ['R-ESC-01']  found [R-ESC-01 0.794  R-REF-05 0.733  R-REF-03 0.676]  gap 0.061  | The refund I'm asking for is 450 TND, who approves that?
top2       p10: expected ['R-ESC-01', 'R-REF-03']  found [R-DEL-02 0.696  R-REF-03 0.695  R-REF-05 0.659]  gap 0.001  | My 620 TND order is 8 days late, refund it
OK         p11: expected ['R-NOT-01']  found [R-NOT-01 0.679  R-DEL-01 0.638  R-DEL-02 0.628]  gap 0.041  | Can you text me when the courier is on the way?
top3       p12: expected ['R-NOT-01']  found [R-DEL-02 0.683  R-DEL-01 0.664  R-NOT-01 0.661]  gap 0.019  | Notify me when my order leaves your warehouse
top2       p13: expected ['R-DEL-01']  found [R-DEL-02 0.765  R-DEL-01 0.742  R-REF-03 0.714]  gap 0.023  | How do you count if an order is late?
OK         p14: expected ['R-REF-03', 'R-DEL-02']  found [R-DEL-02 0.772  R-REF-03 0.751  R-DEL-01 0.670]  gap 0.021  | How many days late before I get compensation?
top2       p15: expected ['R-DEL-02']  found [R-DEL-01 0.689  R-DEL-02 0.678  R-REF-03 0.633]  gap 0.011  | wher is my pakage its late 2 dayz
OK         p16: expected ['R-REF-03']  found [R-REF-03 0.682  R-DEL-02 0.644  R-REF-05 0.623]  gap 0.038  | ordr 4512 week late refund now!!!
OK         p17: expected ['R-RET-01']  found [R-RET-01 0.657  R-DMG-01 0.644  R-REF-03 0.578]  gap 0.013  | I changed my mind about the jacket, it came yesterday, how do I return it?
OK         p18: expected ['R-DMG-01']  found [R-DMG-01 0.738  R-RET-01 0.540  R-DEL-02 0.523]  gap 0.198  | The item works but it's scratched, I have pictures
not scored p19: expected []  found [R-REF-03 0.680  R-DEL-02 0.680  R-REF-05 0.653]  gap 0.000  | I want to cancel my order before it ships
not scored p20: expected []  found [R-REF-05 0.655  R-REF-03 0.650  R-RET-01 0.608]  gap 0.005  | Cancel order 4514 and give my money back, I don't need it anymore

Top 1: 14/18   Top 2: 17/18   Top 3: 18/18   (not scored: 2)
Trace file : C:\Users\mam83\dev\callverse-proto\traces\run_20261028_181332_330666.jsonl
```
**New set (18 scored): top-1 14/18 · top-2 17/18 · top-3 18/18.**

- **Not in the top-2 (1):** p12 "Notify me when my order leaves your warehouse": expected R-NOT-01 (3rd, 0.661).
  Its place was taken by **R-DEL-02** (0.683) and **R-DEL-01** (0.664).
- Not top-1 but in the top-2 (3): p10 (R-DEL-02 beats R-REF-03 by **0.001**; R-ESC-01 is not even in the top 3,
  although the message says 620 TND), p13 (R-DEL-02 beats R-DEL-01), p15 typos (R-DEL-01 beats R-DEL-02).
- Typos: p15 top-2 and p16 OK, so typos alone do not break the search.
- Gaps: 8 of the 18 scored questions have a gap below 0.03 (p01, p04, p10, p12, p13, p14, p15, p17). The search
  often hesitates between 2 rules.
- **Cancellations (not scored):** p19 → R-REF-03 0.680, R-DEL-02 0.680 (gap 0.000). p20 → R-REF-05 0.655,
  R-REF-03 0.650. These scores are **higher** than some correct hits (p07 0.626, p08 0.633), so a score threshold
  could not tell "no rule exists" from a correct hit.

### Old T06 set (`tests/data/policy_search_questions.json`, 10 questions)
**top-1 7/10 · top-2 10/10 · top-3 10/10** (same top-1/top-3 as T06). The 3 top-1 misses (q01, q05, q08) are all
top-2: R-DEL-02 over R-REF-03, R-REF-05 over R-ESC-01 (gap 0.004), R-DEL-02 over R-DEL-01.
Trace `traces/run_20261028_181342_376162.jsonl`.

### The agents' real queries (existing traces only)
Every `policy_search` step, its query, the 2 rules returned, what the agent then cited (proposal `rule_id` or a rule
id in its answer) and what the Coordinator used. "Right rule" = the rule that decides the case from the order's facts
(my reading of the seed data; see Problems). All searches were made by Agent B. Agent A never searched.

**T12** `traces/run_20261024_101903_139840.jsonl` (gpt-oss-120b, 20 held-out live messages): **3 searches**
| # | Message | Query | 2 rules returned | Cited → Coordinator | Right rule in the 2? |
|---|---|---|---|---|---|
| 1 | 4512 6 days late, refund + where 4510 | full refund late delivery over 5 days | REF-03 .818, DEL-02 .812 | REF-03 → approve REF-03 | yes (1st) |
| 2 | (French) 4512 6 days late, refund | full refund days_late >5 not delivered client asks | REF-03 .830, DEL-02 .758 | REF-03 → approve REF-03 | yes (1st) |
| 3 | Cancel order 4514 and refund me | refund order not delivered days_late 0 | DEL-02 .780, REF-03 .778 | none → info | **no**: R-REF-05 (cash on delivery, 0 paid); no cancellation rule |

T12 note: the trace has 6 proposals but only 3 searches. **4 of the 6 proposals cited a rule with no search at all**
(`rule_not_searched`: REF-03 for 4515, for "4512 refund me 100 TND", for "#4512 stuck for ages", and NOT-01 for the
4513 notification). All 4 were approved (the rule was right, the Coordinator checks the condition itself).

**T13c** runs 1–4 (cv-qwen3.5-4b, 24-message practice set): **28 searches**
| Run · trace | Message (practice id) | Query | 2 rules returned | Cited → Coordinator | Right in the 2? |
|---|---|---|---|---|---|
| 1 · `_112928_739365` | d? insult, 4512 week late | order late more than 5 days not delivered client asks for refund | REF-03 .858, DEL-02 .830 | REF-03 (text) → info | yes |
| 1 | d13 return shoes 4508 | return shoes | RET-01 .634, DMG-01 .570 | **DEL-01, DEL-02 (text, not returned)** → info | yes |
| 1 | d14 phone case cracked | damaged item phone case cracked | DMG-01 .693, RET-01 .553 | DMG-01 → ask_proof DMG-01 | yes |
| 1 | d15 refund 4513 | refund request for late delivery | REF-03 .809, DEL-02 .806 | DEL-02 → info | yes |
| 1 | d17 4515 8 days late | order is late and client asks for refund | REF-03 .837, DEL-02 .767 | REF-03 (text) → info | yes |
| 1 | d20 4512 late + 4510 | order late and client asks for refund | REF-03 .836, DEL-02 .766 | REF-03 → approve REF-03 | yes |
| 1 | d24 refund 4512 70 TND | order stuck at depot 6 days late not delivered refund request | DEL-02 .729, REF-03 .725 | REF-03 (text) → info | yes (2nd) |
| 2 · `_143623_961150` | insult, 4512 | order late refund | REF-03 .788, DEL-02 .753 | REF-03 → approve REF-03 | yes |
| 2 | d13 shoes | return shoes order 4508 | RET-01 .641, ESC-01 .616 | RET-01 (text) → info | yes |
| 2 | d14 cracked | damaged item | DMG-01 .758, RET-01 .584 | DMG-01 → ask_proof DMG-01 | yes |
| 2 | d15 4513 | refund request for order 4513 | REF-03 .716, REF-05 .708 | REF-03 (text) → info | yes |
| 2 | d17 4515 | refund request for late delivery | REF-03 .809, DEL-02 .806 | REF-03 (text) → info | yes |
| 2 | d20 | order late and client asks for refund | REF-03 .836, DEL-02 .766 | REF-03 (text) → info | yes |
| 2 | d24 (1st search) | order stuck at depot 6 days late not delivered | DEL-02 .714, DEL-01 .686 | (searched again) | **no**: REF-03 missing |
| 2 | d24 (2nd search) | order not delivered 6 days late | DEL-02 .757, DEL-01 .721 | (searched again) | **no**: REF-03 missing |
| 2 | d24 (3rd search) | full refund | REF-05 .758, REF-03 .755 | REF-03 (text) → info | yes (2nd) |
| 3 · `_144802_368651` | insult, 4512 | order late refund | REF-03 .788, DEL-02 .753 | REF-03 → approve REF-03 | yes |
| 3 | d13 shoes | return shoes order 4508 | RET-01 .641, ESC-01 .616 | RET-01 + **REF-03 (not returned)** (text) → info | yes |
| 3 | d14 cracked | damaged item | DMG-01 .758, RET-01 .584 | DMG-01 → ask_proof DMG-01 | yes |
| 3 | d17 4515 | refund request for late delivery | REF-03 .809, DEL-02 .806 | REF-03 → approve REF-03 | yes |
| 3 | d20 | order is late and client wants refund | REF-03 .829, DEL-02 .766 | REF-03 (text) → info | yes |
| 3 | d24 | order 4512 stuck at depot 6 days late not delivered refund request | DEL-02 .709, REF-03 .701 | REF-03 (text) → info | yes (2nd) |
| 4 · `_150050_334441` | insult, 4512 | order late refund | REF-03 .788, DEL-02 .753 | REF-03 → approve REF-03 | yes |
| 4 | d13 shoes | return shoes order 4508 | RET-01 .641, ESC-01 .616 | **REF-03 only (not returned)** (text) → info | yes |
| 4 | d14 cracked | damaged item | DMG-01 .758, RET-01 .584 | DMG-01 → ask_proof DMG-01 | yes |
| 4 | d17 4515 | refund request for late delivery | REF-03 .809, DEL-02 .806 | REF-03 → approve REF-03 | yes |
| 4 | d20 | order is late and client wants refund | REF-03 .829, DEL-02 .766 | REF-03 (text) → info | yes |
| 4 | d20 (safety-net retry) | order is late and client asks for refund | REF-03 .837, DEL-02 .767 | REF-03 (text) → info | yes |

**Counts (T12 + T13c): 31 queries · right rule in the 2 returned 28/31 (1st place 25/31) · right rule missing 3/31**
(T12 #3 cancel 4514 → R-REF-05 missing; T13c run 2 d24 first 2 searches → R-REF-03 missing, found at the 3rd search).
- Coordinator: in **every** decision that used a rule (8 approve REF-03 + 4 ask_proof DMG-01 in these searched
  cases), the rule was among the 2 returned.
- Agent's cited rule **not** among the 2 returned: 3 answers (d13 run 1 DEL-01/DEL-02, run 3 and run 4 REF-03).
  All 3 were text-only, decision `info`, so no wrong write.
- Extra, also in `run_20261028_*` (T13b context benchmark, 7 runs × 3 messages): 21 searches, right rule in the 2
  **21/21** (1st 18/21; the 3 others are d24 "order stuck at depot…" with DEL-02 .729 just above REF-03 .725).
- `run_20261028_114017_510903` has no search. My own 2 eval traces of today (18:13) are not agent queries and are
  not counted.

### Cut rules (text > 300 characters; agents get `text[:300]`)
| Rule | Length | What the agents see at the end | Lost text |
|---|---|---|---|
| R-REF-05 | 313 | "…For a cash-on-delivery order that is not yet paid, the amount paid is 0 TND, so no refund" | `" is possible."` (13 chars) |

The other 7 rules are 153–287 characters and arrive complete. The cut is harmless: "so no refund" keeps the meaning.

### Time and calls
About 18:12 → 18:20 (~10 min of 1 h). API calls: 0 (only the local bge-small embeddings). Agent runs: 0.

### Is the RAG good enough? (3 sentences)
For today's 8 rules, yes: the agents' real queries got the right rule in the 2 returned 28/31 times, and every
Coordinator decision used a rule that the search had returned. Its weakest case is the look-alike delivery family
(R-DEL-01 / R-DEL-02 / R-REF-03, and R-NOT-01 when the words are "order leaves warehouse"): gaps of 0.001–0.03 decide
the order. A related problem: a query that names the order's status ("stuck at depot, 6 days late") instead of the
request (refund) misses R-REF-03, and with no score floor a cancellation question gets refund rules that look like
answers. What to fix first (suggestion only): add a cancellation rule, or tell the agent "no rule" when nothing
fits. Then make the delivery rules easier to tell apart, for example by embedding a few example questions per rule
or by adding words to the titles. Any such change must be measured on a new held-out set, not on v2.

## 4. Problems
- **"Right rule" for the agents' real queries is my own reading** of the seed facts. Two cases need the Brain's
  judgment:
  - T12 "Cancel order 4514 and refund me": I counted R-REF-05 as right (cash on delivery, 0 paid), but there is no
    cancellation rule.
  - d24 "refund 4512 70 TND": I counted R-REF-03 (it allows the refund; the Coordinator caps 70 → 59.9 in code).
    R-REF-05, the rule that caps the amount, was returned only once in the 5 d24 searches of T13c (0 of 7 in T13b).
  If R-REF-05 is the right rule for d24, the count drops from 28/31 to 26/31.
- **The agents sometimes cite rules from memory.** T12 (gpt-oss-120b): 4 of 6 proposals cited a rule with no search,
  which is only a warning today (`rule_not_searched`). T13c: 3 answers named a rule that the search had not returned.
  None caused a wrong write, but it goes against "facts come from tools".
- p10 ("620 TND, 8 days late"): R-ESC-01 is not in the top 3. The Coordinator applies the 300 TND limit from code
  (`layer3_threshold()`), so the agent does not need the rule, but its reply could miss "needs approval" if it
  relied on the search.
- Small sample: 18 scored questions and 31 real queries, most of them about 4512. One question changes top-2 by ~6 %.
- The trace listing was made with a one-off read-only script in my scratchpad (not committed: the task allows only
  the eval-script change). The tables above are its output, checked by hand.

## 5. Questions for the Brain
1. Do you agree with the "right rule" for the 2 unclear cases (4514 cancel → R-REF-05; d24 → R-REF-03)?
2. Should `rule_not_searched` stay a warning only? T12 shows the strong model cites rules without searching in 4/6
   proposals.
3. Do you want the trace-reading script committed (e.g. `scripts/list_policy_searches.py`) so this check can be re-run
   after a RAG fix?

## 6. Next step
Suggestion: a small task to (a) add a cancellation rule from the teammate's platform, or a "no matching rule" answer,
and (b) make R-DEL-01 / R-DEL-02 / R-REF-03 / R-NOT-01 easier to tell apart. Measure it on a **new** held-out set v3
(v2 is now used) and with the real-query listing above.
