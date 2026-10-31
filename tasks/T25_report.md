# T25 report — fine-tuned embedding models on the PC

## 1. In plain words
I tested the two models the Brain fine-tuned on Colab against today's M3 model, on the validation data only, on Yassine's
PC. The small fine-tuned model is better at spotting ShopNova reasons, but it is worse on Atlas and much worse at
finding the right company rule (30 of 30 falls to 22 of 30), and it hardly ever hands a doubtful message to the LLM.
It therefore fails two of the four conditions fixed in advance, so by our rule nothing changes: the system keeps bge-small
with its current settings. The locked test sets were not opened.

## 2. Done
- Step 0: branch `feature/t25-ft-embeddings` from main (de24fa3). Step 1: both zips unpacked in `models/` (git-ignored).
- `benchmarks/m3/t25_score.py`: scores one model per process with the T23 grid, tie rule and measures, plus PC speed and peak RAM
  (`results/t25/*.json`). Docs: `docs/benchmarks/M3.md` section 9. README updated. No change to config, code of the system, tests.
- Not done (by the stop rule): steps 4-7 (locked test, switch, tests change, live check).

## 3. Evidence
Step 1: both load with `SentenceTransformer(path, device="cpu")`: bge-small-ft 384 dims, bge-base-ft 768 dims; training file:
bases BAAI/bge-small / bge-base-en-v1.5, 3,149 rows, 14 labels (8 Atlas + 6 ShopNova), seed 2026, 2 epochs, batch 32, lr 2e-5, BatchAllTripletLoss.

Step 2 (val: ShopNova 328, Atlas 40, search 30 + 5):

| | settings | macro-F1 S / A / avg | critical S / A | needs-LLM S / A | top-1 / top-2 / MRR (no prompt) | top-1 / top-2 / MRR (prompt) | Intake p50 / p95 | search p95 | RAM |
|---|---|---|---|---|---|---|---|---|---|
| bge-small (today) | k5, .69 / .54 | .411 / .884 / **.647** | 26 / 1 | 40.6 / 2.5 % | .900 / .967 / .944 | .900 / **1.000** / .950 | 16 / 21 ms | 17 ms | 663 MB |
| bge-small-ft | k1, .63 / .54 | .503 / .853 / **.678** | 22 / 2 | 2.4 / 0 % | .467 / .733 / .664 | .500 / .700 / .675 | 15 / 21 ms | 16 ms | 663 MB |
| bge-base-ft (record) | k1, .71 / .57 | .618 / .898 / .758 | 17 / 2 | 1.8 / 0 % | .333 / .600 / .568 | .333 / .500 / .543 | 28 / 47 ms | 32 ms | 1018 MB |

The reference reproduces T23 / T24 exactly (0.647, 26 critical). Better search variant per model: today = with prompt; ft = no prompt (22/30 vs 21/30).
Step 3 verdict for bge-small-ft: avg macro-F1 >= 0.667 **PASS** (0.678) · Atlas F1 >= today's **FAIL** (0.853 < 0.884) · search top-2 30/30 **FAIL** (22/30) · p95 <= 100 ms, RAM <= 1.5 GB **PASS**.
→ **loses; no locked test, no switch.** Tests: not touched (no code of the system changed; the T24 suite was 1048/1048 on this main).
`git status`: no models, `.env`, raw data staged.

## 4. Problems
- Speeds are much lower than in T24 (bge-small Intake p95 21 ms vs 60 ms): the PC was less loaded. Compare rows, not absolutes.
- The fine-tune was trained with our reason examples, which are also the Intake index, so its gain on ShopNova may be partly memory of those examples.
- bge-small-ft says "needs LLM" for only 2.4 % of ShopNova messages: it answers instead of asking, so 22 critical errors still remain.
- Atlas val has only 40 messages: one message moves its F1 by about 0.02-0.03.

## 5. Questions for the Brain
1. Use the fine-tuned model for Intake only and keep today's model for rule search (two models in memory)? It would fail the Atlas condition, so not done; your call.
2. Retrain without the Atlas-poor balance / with a search objective (the search collapse suggests the triplet loss hurts free-text retrieval)?

## 6. Next step
Close T25 with no switch. If the fine-tune is worth another try, a second Colab run with a contrastive (question → rule) objective added, scored with the same script.

**Does the system switch? No. It is unchanged and safe for the demo.**
