# T32 report — Wrap-up after the held-out check

**Top line:** the agent bench now counts both kinds of wrong proposals. Re-summarised offline (no model call), T31 shows
`Wrong proposals: 3 (acted when it should not: 0, called a forbidden tool: 3 ['C09', 'C12', 'C14'])`. Before, the line
said 0. The T31 report has the C12 note: official 6/10, lenient 7/10. `docs/findings_agent_c.md` explains the finding
for the teacher. Tests **1879/1879** (main 1877, +2). The held-out file was not run and not changed. Nothing changed in
`callverse/`.

## 1. In plain words
The test script for the agents used to say "0 wrong proposals" after the hidden test, which was misleading: Agent C
had in fact proposed 3 things the tests forbid. Now the script counts those too, and shows the two kinds apart. We
re-printed the hidden test's summary from its saved results, without running any model again. We also wrote a short,
simple page that explains what the hidden test found about Agent C, and why the rules still stopped every mistake.
The style policy stays OFF.

## 2. Done
- `scripts/eval_agents.py`:
  - New `wrong_proposals(cases, runs)`. It returns `acted` (a proposal where the case expects none), `forbidden`
    (a tool from the case's `must_not_call` was called), and `total` (runs with either; a run with both counts once).
  - The summary moved into `print_summary(...)`, with the new line
    `Wrong proposals: N (acted when it should not: a, called a forbidden tool: b [ids])`.
  - New `--summarize RUNS.json`: prints the summary from a saved runs file. It runs no case and calls no model.
    `--model` is now needed only without `--summarize`. The held-out guard (`--heldout`) still applies.
- `tests/test_eval_agents.py`: 2 new tests (fake runs, no model):
  - both kinds are counted, and a run with both counts once;
  - `--summarize` never runs a case or forces a model.
- `tasks/T31_report.md`: "Note (T32)" under the top line (C12: official 6/10, lenient 7/10; the corrected
  wrong-proposal line). Copy in `out/T31_report.md`.
- `docs/findings_agent_c.md` (new): the finding for the teacher. It is linked from `docs/architecture.md` (one line,
  under the safety rules) and from README (T32 line).

## 3. Evidence
- **Full suite: 1879/1879** (207 s). Bench tests `tests/test_eval_agents.py` + `test_eval_policy_search.py`: 9/9.
- **T31 re-summarised offline:**
  `python -m scripts.eval_agents --file tests/data/agents_heldout_cd.json --heldout --summarize out/t31_heldout_cd.json`
  ```
  Model ollama/callverse-m2-v3
    Agent C: 3/7 pass, avg 25.9s
    Agent D: 3/3 pass, avg 9.1s
    Total: 6/10 pass
    Wrong proposals: 3 (acted when it should not: 0, called a forbidden tool: 3 ['C09', 'C12', 'C14'])
    Agent D owner notes worded by the model: 9, by the template: 0
    Non-local model calls: none
  ```
  As the task expected, b = 3 (C09, C14, C12). The same pass counts as T31.
- **Checks:**
  - `git diff b4ad04d HEAD -- tests/data/ callverse/` is empty: the held-out file is unchanged and not run, and
    nothing changed in `callverse/`.
  - Files changed: `README.md`, `docs/architecture.md`, `docs/findings_agent_c.md`, `scripts/eval_agents.py`,
    `tests/test_eval_agents.py`, `tasks/*`.
  - Nothing under `models/` or `data/raw/`, and no secrets.
- `config.yaml` is untouched: the style policy stays OFF.

## 4. Problems
- `--summarize` needs the case file to know each case's `must_not_call` (saved runs do not store it). For the held-out
  file this means reading it with `--heldout`. It is read only, never run.
- The lenient 7/10 is a reading of the result, not a re-score. The bench still scores C12 as a fail.

## 5. Questions for the Brain
None.

## 6. Next step
Decide whether to turn the style policy ON for the demo (see one demo reply with it on first). Optional: the Console
"Learning" page (T30 step 9).

Merge line for Yassine (after the Brain's review): `git checkout main && git merge --no-ff origin/feat/t32-wrapup`
