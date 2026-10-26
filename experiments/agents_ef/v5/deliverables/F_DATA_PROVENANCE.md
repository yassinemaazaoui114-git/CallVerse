# F1 — Data provenance and audit (Agent F, v5)

**Worker F, v5, 2026-10-26.**
- Code: `v5/f/data_audit.py`. Results: `v5/f/results/f1_data_audit.json`. Figure: `v5/f/figures/f1_label_dist.png`.
- Earlier records reused, not redone: `v3/f/DATASETS.md`, `v3/f/data_provenance.json`, `v4/f/DATASETS_RECHECK.md`.

## In plain words

- Agent F's models are trained and tested on one public research dataset (USS). It holds English task dialogues and Chinese e-commerce service chats.
- In USS, 3 to 7 hired annotators read each dialogue and gave it a 1–5 satisfaction score. The customers themselves gave no score.
- The three parts (train / validation / test) share no conversation: not exactly, not after normalising the text, and not as near-copies.
- I found no real personal data in a spot-check. The Chinese part was anonymised by its publishers.
- There is **no labelled French support dialogue** anywhere we can use. French product reviews (Amazon) exist, but they rate products, not support. They are kept as a separate side benchmark.

## 1. Datasets used in v5, and their label definitions (label types are never mixed)

| Dataset | Used for | Label definition | Who labels | Licence / terms | Status |
|---|---|---|---|---|---|
| **USS** (Sun et al., SIGIR 2021): SGD, MWOZ, ReDial, CCPE (EN), JDDC (ZH) | every v5 model (TRAIN / VAL / TEST) | dialogue-level OVERALL satisfaction 1–5; target = **mean of 3–7 annotators** | third-party annotators | GitHub repo has no LICENSE file; HF mirror says MIT; the source corpora keep their own terms (**JDDC: research only**). Academic use with citation; no raw text in git | USED (unchanged V3 split files, SHA256 below) |
| Amazon Multilingual Reviews EN/FR | **not used in v5**; V3 auxiliary results only | product stars 1–5, written by the customer about a **product** | the customer | Amazon terms (research) | AUXILIARY, separate |
| USS turn-level ratings | **never an input** | per-turn satisfaction | annotators | — | not used |

**Split files** (`$FV3/data_uss`, made by `v3/f/uss_data.py`, 70/15/15 by dialogue, stratified per sub-corpus, seed 13). SHA256:
- train `30528794…bc17923e`
- val `3cff97a2…78d01a46`
- test `36bdb7b6…2fb061090`
- Full values are in `f1_data_audit.json`.

## 2. Audit results

| Check | Result |
|---|---|
| Exact duplicate texts within a split / across splits | **0 / 0** |
| Normalised duplicates (NFKC, lower case, digits → 0, punctuation / spaces / role tags removed) within / across | **0 / 0** |
| Near-duplicates: char 3–5-gram TF-IDF cosine to the nearest TRAIN dialogue (vectoriser fitted on TRAIN) | VAL median 0.40, 99th percentile 0.68; TEST 0.40 / 0.67. **No pair ≥ 0.8** |
| Does the nearest TRAIN neighbour leak the label? | mean \|label − neighbour's label\| = 0.52–0.53, vs 0.69 for a random TRAIN dialogue. This is weak topical similarity (same sub-corpus), not copying |
| Languages with labels | **EN 2,450 / 525 / 525** and **ZH 2,290 / 491 / 491** (train / val / test). **FR: 0** labelled support dialogues |

**Label distribution** (mean annotator rating):

| Split | n | mean | SD | rounded counts 1/2/3/4/5 | share ≤ 2.5 (dissatisfied) | share ≥ 4 |
|---|---|---|---|---|---|---|
| TRAIN | 4,740 | 3.45 | 0.60 | 2 / 164 / 2,299 / 2,182 / 93 | 4.7% | 25.1% |
| VAL | 1,016 | 3.46 | 0.62 | 2 / 36 / 478 / 477 / 23 | 5.2% | 26.1% |
| TEST | 1,016 | 3.45 | 0.63 | 1 / 48 / 481 / 457 / 29 | 6.1% (62) | 25.3% (257) |

- EN sub-corpora: means 2.97–3.24, SD 0.35–0.47, 0.7–7% at ≥ 4.
- JDDC: mean 3.76, SD 0.63–0.67, ~49% at ≥ 4.
- The extremes are rare. Class 1 has **1** TEST dialogue and class 5 has **29**, so per-class numbers for 1 and 5 are anecdotal.

## 3. Privacy spot-check (regex counts per sub-corpus; only counts are written; matches were read in the terminal and not saved)

| Pattern | SGD | MWOZ | ReDial | CCPE | JDDC | What the matches are |
|---|---|---|---|---|---|---|
| e-mail | 0 | 0 | 0 | 0 | 0 | — |
| phone-like (≥ 7 digits) | 320 | 466 | 0 | 0 | 1,921 | SGD: synthetic numbers from SGD's fake database. MWOZ: Cambridge venue numbers and generated taxi numbers from the MultiWOZ database. JDDC: pseudonymised 8-digit ids (`[ORDERID_…]`-style) |
| URL | 0 | 0 | 4 | 0 | 500 | ReDial: public film / web pages. JDDC: jd.com product and help pages |
| card-like (13–19 digits) | 0 | 0 | 0 | 0 | 1 | one 14-digit JDDC string, in an order / tracking context, inside an anonymised dialogue |
| JDDC anonymisation placeholders (`[数字x]`, `[金额x]`, `[ORDERID_…]`…) | — | — | — | — | 3,244 dialogues | the publisher's de-identification |

**Verdict:** no real customer PII found. USS raw text is still kept outside git, under its research-only terms.

## 4. Alibaba / Taobao service-satisfaction data (licence and label definition only; not downloaded)

| Item | Finding | Source |
|---|---|---|
| Dataset | Song et al., EMNLP 2019, "Using Customer Service Dialogues for Satisfaction Analysis with Context-Assisted Multiple Instance Learning" (Alibaba Group). Two Chinese Taobao customer-service corpora: **Clothes** (10,000 dialogues) and **Makeup** (3,540) | https://aclanthology.org/D19-1019.pdf |
| Label definition | "Both datasets have service satisfaction ratings in 1-5 stars from customer feedbacks", used as 3 classes (1–2 unsatisfied / 3 met / 4–5 satisfied); Clothes: 2,302 / 6,399 / 1,299 | paper §5.1, Table 1 |
| Label type | **Genuine customer ratings** of the service interaction. This is the only label type that could open the F→E gate. But it is Chinese only and e-commerce on a different platform | — |
| Release / licence | Released at github.com/songkaisong/ssa (`clothes.zip`, `makeup.zip`). The repository shows **no LICENSE file**, and its README says nothing about terms. The data derive from Taobao platform logs (Alibaba terms apply) | repository page |
| Verdict | **NOT DOWNLOADED.** With no licence, the default is all rights reserved, so use needs written permission from the authors. Whether the released files keep the 5-star value or only the 3 classes is not stated. **Recommended action:** Yassine / the supervisor e-mails the authors for research permission. If granted, it would be a ZH domain check with customer labels, never mixed with USS annotator labels |
| JDDC | already inside USS (JD.com service chats, annotator labels). Not a separate dataset | `v3/f/DATASETS.md` |
| Also seen | EST dataset (arXiv 2603.03327): **simulated** user–agent service dialogues, labelled per turn. Not genuine. Not a candidate | search result |

## 5. Genuine CallVerse ratings: none exist (verified again)

- The ShopNova database schema has the tables users, products, orders and refunds. **No rating or feedback column.**
- `grep` for `rating|csat|satisfaction` in the 4 local CallVerse checkouts (code, data, configs; `experiments/` excluded) finds only `callverse/slm/dev_decisions.json`: AI-written SLM examples, no rating field.
- Traces: of 267 trace files found, the only ones with `pipeline_done` are the 6 scripted demo copies in `v4/f/demo_traces/`. **No unscripted closed conversation exists** (see `F_DOMAIN_VALIDATION.md`).
