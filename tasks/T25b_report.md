# T25b report — LoRA adapter on bge-small

## 1. In plain words
I tested the small "adapter" the Brain trained on Colab. It sits on top of the frozen bge-small and is switched on only for
Intake. It does what it was designed for: rule search stays perfect (30 of 30) because search uses the untouched model.
But for Intake the adapter is not better than today's model: its average score on validation is 0.642 (we needed 0.667) and
on Atlas it drops from 0.884 to 0.791. By the rule fixed in advance it loses, so nothing changes and the locked tests
were not opened.

## 2. Done
- Step 0: branch `feature/t25b-lora` from main (cac2490); task file, NEXT.md and the Brain's three files committed first.
- Step 1: adapter unzipped to `models/bge-small-callverse-lora/` (git-ignored). `peft` is **not installed** and I added no
  library: `t25_score.add_lora` merges the adapter into the base weights (W + alpha/r·B·A) on the pinned revision. Checks:
  ON ≠ base (max vector difference 0.23); the plain base object is untouched (identical to a fresh load).
- Step 2: `t25_score.py` got the key `bge-small-lora` (two model objects in one process: plain for search, merged for Intake).
- Docs: M3.md section 10, DATA_LICENCES.md (Bitext + ABCD), README. Steps 4-7 not done (stop rule). No system code or tests changed.

## 3. Evidence (validation only; `benchmarks/m3/results/t25/bge-small-lora.json`)
| | settings | macro-F1 S / A / avg | critical S / A | needs-LLM S / A | search top-2 (adapter off) | Intake p50 / p95 | search p95 | RAM |
|---|---|---|---|---|---|---|---|---|
| bge-small today (= T25 row, same settings) | k5, .69 / .54 | .411 / .884 / .647 | 26 / 1 | 40.6 / 2.5 % | 30/30 | 16 / 21 ms | 17 ms | 663 MB |
| bge-small + LoRA | k1, .54 / .52 | .493 / .791 / .642 | 25 / 1 | 5.2 / 0 % | 30/30 (adapter on: 20/30) | 11 / 18 ms | 15 ms | 810 MB (2 objects) |

Verdict: avg ≥ 0.667 **FAIL** (0.642) · Atlas ≥ 0.884 **FAIL** (0.791) · search 30/30 off **PASS** · p95 ≤ 100 / 200 ms, RAM ≤ 1.5 GB **PASS**.
→ **loses; no locked test, no switch.** Tests: not run (nothing in the system changed; main had 1048/1048). `git status`: no models, `.env`, raw data staged.

## 4. Problems
- `peft` missing on the PC; I avoided it with a manual merge. If the switch is ever wanted, that merge function moves into `callverse/` (it is about 12 lines).
- Atlas validation is 40 messages: one message is about 0.025 of F1. Still, 0.791 vs 0.884 is a loss of about 4 messages.
- Speeds are lower than T24 because the PC is less loaded: read the rows, not the absolutes.

## 5. Questions for the Brain
1. The adapter's Atlas result is worse than the plain model although it was trained with 120 Atlas messages. Is the Bitext Travel data too unlike our Atlas messages? A next try would train on Atlas-like data only for Atlas.
2. Stop fine-tuning M3 here? Today's bge-small (k5, .69/.54, prompt in search) stays the best within the limits after T24, T25 and T25b.

## 6. Next step
Close T25b with no switch.

**Does the system switch? No; it is unchanged and safe for the demo.**
