# Agent F v3 — datasets checked (2026-10-25)

The full records (URLs, revisions, SHA256 values, schemas, counts) are in `data_provenance.json`.
The USS statistics are in `results/uss_stats.json`, produced by `uss_data.py`.

**Local CallVerse datasets: BLOCKED.**
- This sandbox cannot reach the user's Windows PC (`C:\Users\semah\...`).

## Verdicts

| ID | Dataset | Label | Real or synthetic | Verdict |
|---|---|---|---|---|
| A | **USS** (Sun et al. 2021): SGD, MWOZ, ReDial, CCPE (EN) and JDDC (ZH) | dialogue-level and turn-level satisfaction 1–5, 3–7 annotators | real dialogues; labels are third-party annotator judgements | **USED: primary benchmark** (EN and ZH reported separately) |
| B | DialEval-2 / DCH-2 (NTCIR helpdesk) | dialogue quality / customer satisfaction scores | real helpdesk dialogues | **NOT ACCESSED**: a user agreement is required. High-value future dataset. |
| C | Amazon Multilingual Reviews EN/FR | product stars 1–5 (self-reported) | real | **AUXILIARY**: v2 subset and results reused |
| D | Saif7800/customer_qa_dataset | `csat` 1–5 | **SYNTHETIC** (LLM-generated; CSAT is almost a function of the sentiment tag) | **REJECTED** as ground truth. Not used. |
| E1 | sharmila122125/customer-support-csat (Flipkart CSAT) | survey CSAT 1–5 | looks operational; upstream licence not verified | **CANDIDATE**, not benchmarked: no dialogue text; the remark is written together with the score |
| E2 | rootfs/user-satisfaction-dataset | 4 classes (SAT / clarify / wrong / different) | derived from public data | **REJECTED**: not a satisfaction rating |
| E3 | Kaggle "Customer Support Ticket Dataset", LEGO corpus | CSAT / interaction quality | — | **NOT ACCESSED** (Kaggle needs a login; LEGO left for later) |

## A. USS — what was verified

- **Source files**
  - The original TXT files were taken from `github.com/sunnweiwei/user-satisfaction-simulation` (`dataset/`).
  - Reason: they keep **every annotator's rating** and include JDDC.
  - The HF mirror `akomma/uss-ratings-dataset` is a parquet file with only the 4 English sub-datasets.
  - The mirror was downloaded, but its rows were **not parsed** (there is no parquet reader in the venv).
- **Licence**
  - The GitHub repo has no LICENSE file. The HF mirror says MIT.
  - The source corpora have their own terms (JDDC is research-only).
  - Use: academic research with citation. No raw text in git.
- **Size**: 6,800 dialogues (3,500 EN + 3,300 ZH). All have an OVERALL rating. 28 duplicate JDDC dialogues were dropped, leaving 6,772.
- **Labels, OVERALL** (from `results/uss_stats.json`):

| Sub | Dialogues | Mean (std) of mean rating | Rounded mean rating counts | Krippendorff α (OVERALL) | α (turn) | All annotators agree |
|---|---|---|---|---|---|---|
| SGD | 1,000 | 3.214 (0.387) | 2:23, 3:678, 4:299 | 0.225 | 0.249 | 25.8% |
| MWOZ | 1,000 | 3.122 (0.366) | 1:2, 2:29, 3:780, 4:188, 5:1 | 0.199 | 0.189 | 29.7% |
| ReDial | 1,000 | 3.225 (0.451) | 1:1, 2:40, 3:640, 4:314, 5:5 | 0.280 | 0.233 | 21.1% |
| CCPE | 500 | 3.020 (0.352) | 2:22, 3:422, 4:56 | 0.202 | 0.197 | 32.2% |
| JDDC | 3,300 | 3.756 (0.635) | 1:2, 2:135, 3:746, 4:2276, 5:141 | 0.524 | 0.686 | 29.7% |

- **Reading the English labels**
  - The English labels are nearly constant: about 70–85% of dialogues round to 3.
  - Agreement is low (α 0.20–0.28), so they are hard to predict, and the MAE of a constant predictor is already small (about 0.3–0.4).
  - The useful signals are the ranking (Spearman) and the gain over the per-corpus floor.
- **JDDC**
  - JDDC is **real e-commerce customer service** (JD.com), so it is the closest to ShopNova.
  - Its labels spread more and agree better (α 0.52).
- **Turn ratings versus OVERALL**: correlation of the last-turn rating with OVERALL = 0.61 / 0.61 / 0.67 / 0.53 / 0.31 (SGD / MWOZ / ReDial / CCPE / JDDC). This is a label-versus-label analysis only; turn ratings are never an input.
- **Split**
  - 70/15/15 by dialogue, stratified per sub-dataset. Train / val / test = 4,740 / 1,016 / 1,016 (per-sub counts in `results/uss_stats.json`).
  - EN: 2,450 / 525 / 525. ZH: 2,290 / 491 / 491.

## B. DialEval-2 / DCH-2

- Real customer-helpdesk dialogues with satisfaction-type annotations by several annotators.
- Access requires signing a user agreement, so it was **not accessed**.
- Recommended as the next dataset if Yassine or the teacher signs the agreement. It matches Agent F's task better than USS-EN.

## C. Amazon EN/FR

- The subset, its provenance and the v2 results are reused: `results/leaderboard_amazon.json` lists each source file with its SHA256.
- The label is **product** satisfaction (stars). It is not satisfaction with a support interaction, so it is reported separately.

## D. Saif7800/customer_qa_dataset

- The training file is 1.37 GB, so only the first 3 MB of `validation_complete.jsonl` (939 rows) was inspected.
- 99% of rows have `source = llm_generated_v6_augmented`.
- `csat` follows the `sentiment` tag almost exactly:
  - urgent → 3 (208/208)
  - confused → 3 (208/208)
  - positive → 4 or 5
- "unresolved" conversations often get CSAT 4–5.
- This is synthetic and its labels are rule-derived, so it is **not used**.
