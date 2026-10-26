# Client Simulator handover - S2 + D5 + D6 (one page)

**Judging note.** Realism and stays-in-role scores (0-6) were judged by Claude Code (Test 1 blind: anonymous codes, shuffled order) and were **not hand-verified** by a person. The outputs are in JUDGE_SPOTCHECK.md and JUDGE_SPOTCHECK_FINAL.md for review.

## TASK3 update: lean simulator (S1 = Qwen, so no Qwen)
**Final setup: `gemma3:1b` writer + fine-tuned MiniLM scorer with the quantile setting (CPU).** The writer needs 828 MiB (0.83 GB) of GPU memory; together with the agents' qwen2.5:3b both used 2,854 MiB on our 6 GB card, so the pair should fit a 4 GB laptop GPU (not tested on a 4 GB card). The scorer needs no GPU (about 10 ms per score). Previous setup: phi4-mini for both.

**Open team question:** the Flipkart CSAT and USS licences are still unconfirmed (BLOCKERS.md B1, B2). The MiniLM
scorer was trained partly on them; if they cannot be confirmed, retrain it without them (Olist + TripAdvisor only) before
anything is published.

### Final comparison (writer on the same 30 role cards; scorer on the same 1,000 real Flipkart CSAT test rows)

| Setup | GPU memory alone | GPU memory with qwen2.5:3b | Seconds per turn | Realism distance (lower = better) | Realism (0-6) | Stays in role (0-6) | Score MAE [95% CI] | Score QWK [95% CI] | Distance to real score distribution |
|---|---|---|---|---|---|---|---|---|---|
| **Before:** phi4-mini:3.8b writer + phi4-mini LLM scoring (main calibration) | 2510 MiB | 4534 MiB | 0.71 s | 0.177 (no examples) / 0.204 (5 examples) | 5 | 5 | 0.92 [0.84, 1.00] | 0.31 [0.24, 0.38] | 0.33 |
| **After:** gemma3:1b writer + MiniLM int8 CPU scorer (quantile setting) | 828 MiB (+0 GPU for the scorer) | 2854 MiB | 0.47 s + 9.88 ms per score (CPU) | 0.150 | 6 | 5 | 0.80 [0.72, 0.87] | 0.40 [0.33, 0.47] | 0.06 |

Seconds per turn and memory: same prompt, Ollama with KV q8_0 + flash attention, num_ctx 1024, requests to 127.0.0.1 (with 'localhost' Windows adds about 2 s per request; all earlier phases include that overhead). Memory with qwen2.5:3b = nvidia-smi increase with both models loaded.

The fine-tuned writer (LoRA on gemma-3-1b-it, 5,000 real tweets) was less realistic than the prompted base model and could not
be exported to Ollama (needs approval to run the llama.cpp converter; BLOCKERS.md B13). The fine-tuned scorer is the best scorer
on real customer scores. All tests on held-out real data; see FINETUNING.md and DATA_SOURCES.md.

---


**Picks.** Simulator LLM: **qwen3.5:4b** (Qwen, Apache 2.0), runner-up **phi4-mini:3.8b** (Phi, MIT).
Real messages: **Customer Support on Twitter** (CC BY-NC-SA 4.0). Real numbers: **Twitter timestamps** + **CA Medi-Cal
call-center data** (CHHS Terms of Use, attribution). Real scores with confirmed licence: **TripAdvisor Hotel Reviews** (CC BY-NC 4.0) and
**Olist** (CC BY-NC-SA 4.0, Portuguese); the two sets that fit best and were used to calibrate (Flipkart CSAT, USS)
are **licence to verify**.

**Decision needed:** CallVerse already uses qwen2.5:3b (Qwen) to write replies. If S1 = Qwen, or we count the writer
as S1, switch the simulator to phi4-mini (one line in `simulator/config.yaml`; its calibration is already shipped).

**What the simulator is validated for - and what it is not.** The Client Simulator is validated for realistic
satisfaction-score **distributions**: its calibrated scores match the real customer CSAT distribution overall
(Wasserstein distance 0.24 on test vs 0.68 for "always 5"), and with the delay-aware calibration the mean score per
waiting-time bucket is on average within 0.22 points of the real mean (still too low for waits over 8 hours). It is **not** a
per-conversation satisfaction predictor: its item-level agreement with real scores is modest (test QWK 0.33).
Predicting the satisfaction of one specific conversation is **M7's job** (agent F's predictor). The bar M7 must beat
is the CPU baseline from D6: **TF-IDF + logistic regression, QWK 0.42 (MAE 0.55) on the 200-row CSAT test sample**
used for all model comparisons (on the full CSAT test split: QWK 0.363 over all 12,887 rows, 0.675 over the 4,312
rows that have a customer remark; `results/p1_baselines.json`, `results/p3_test3_scores.json`). An M7 model that
does not beat these numbers on the same test rows adds nothing over the baseline.

## S2 - simulator LLM (Q4_K_M in Ollama, RTX 3060 6 GB; Test 1 judged by Claude Code, blind)

| Model | Family | Size | GPU memory (alone / next to qwen2.5:3b) | Realism (0-6) | Stays in role (0-6) | s / message | Realism distance* | CSAT QWK / MAE (test, n=200) | CONV QWK (test, n=120) | Licence |
|---|---|---|---|---|---|---|---|---|---|---|
| **qwen3.5:4b** | Qwen | 4.2B | 3,000 / 5,733 MiB, fits | 6 | 5 | 3.06 | 0.164 | 0.33 / 0.80 | 0.18 | Apache 2.0 |
| **phi4-mini:3.8b** | Phi | 3.8B | 2,957 / 5,043 MiB, fits | 5 | 5 | 3.18 | 0.177 | 0.27 / 0.93 | 0.17 | MIT |
| granite4:3b | Granite | 3.4B | 2,391 / 4,477 MiB, fits | 5 | 4 | 3.25 | 0.187 | 0.30 / 1.11 | 0.13 | Apache 2.0 |
| gemma3:4b | Gemma | 3.9B | 2,772 / 5,751 MiB, fits | 6 | 5 | 3.01 | 0.248 | 0.26 / 1.11 | 0.15 | Gemma Terms |
| llama3.2:3b | Llama | 3.2B | 2,442 / 4,529 MiB, fits | 5 | 4 | 2.85 | 0.218 | 0.30 / 0.99 | 0.07 | Llama 3.2 Community |
| mistral:7b | Mistral | 7.2B | 4,148 / does not fit | 3 | 5 | 3.68 | 0.284 | 0.35 / 0.64 | 0.19 | Apache 2.0 |
| UserLM-8b | Llama (user simulator) | 8.0B | 4,187 / does not fit | 2 | 3 | 5.01 | 0.309 | 0.28 / 0.63 | 0.08 | MIT, Llama 3.1 base: to verify |

*Realism distance to real customer messages, no examples; 0 = identical. Baselines on the same test items: CSAT
"always 5" QWK 0.00 / MAE 0.68, TF-IDF+LR 0.42 / 0.55; CONV "always 3" QWK 0.00 / MAE 0.30.
**No model is significantly better than another on score match** (paired bootstrap; QWK 95% interval about +-0.17).

## D5 - real messages and numbers

| Source | Licence | Gives | Size | Domain |
|---|---|---|---|---|
| **Customer Support on Twitter** (Kaggle thoughtvector) | CC BY-NC-SA 4.0 | first messages, replies, threads, timestamps | 165,747 English first messages kept (16 brands) | Amazon/UPS/Target/Argos/eBay + 11 airlines, rail, Airbnb |
| Twitter US Airline Sentiment (Kaggle crowdflower) | CC BY-NC-SA 4.0 | complaint reasons (annotators) | 14,640 tweets | US airlines |
| **CA County Medi-Cal call-center data** (data.chhs.ca.gov) | CHHS Terms of Use (free use with attribution) | abandonment, volume, wait | 180 county-months | public benefits |
| Flipkart CSAT (Kaggle ddosad) | to verify | reason mix, arrivals, response times | 85,907 contacts | e-commerce |
| Technion SEE Lab bank call-center data | to verify | arrivals, abandonment | to verify | bank |

Key numbers: reason mix (Flipkart, mapped) return_item 40.4%, other 32.2%, late_delivery 9.7%, order_status 8.6%,
refund 5.3%, damaged 3.7%. Arrivals peak 16:00-17:00 UTC (6.1-6.2%/h), Friday busiest (16.7%). Brand first reply:
median 14.3 min (shops), 10.1 min (travel). Abandonment (Medi-Cal): median 0.28 = **28% of queued calls** (unit confirmed in the source data dictionary).
Real first message: median 20 words, 30% with a spelling error, 21% with "!", 10% with an emoji. Keyword reason
mapping: 76% correct on a 50-message hand check.

## D6 - real satisfaction scores

| Dataset | Licence | Text | Score (who) | Size | Language |
|---|---|---|---|---|---|
| Flipkart-style CSAT (Kaggle ddosad) | **to verify** | remark | CSAT 1-5 (customer) | 85,907 (28,742 with remark) | English |
| USS MultiWOZ + SGD (GitHub) | **to verify** | conversation | 1-5 (annotators) | 1,235 travel dialogues | English |
| **TripAdvisor Hotel Reviews** | CC BY-NC 4.0 | review | 1-5 (customer) | 20,491 | English |
| **Olist reviews** | CC BY-NC-SA 4.0 | review | 1-5 (customer) | 99,224 | Portuguese |
| Airline Reviews (Skytrax) | to verify | review | 1-10 (customer) | 23,171 | English |
| Support Ticket Dataset | CC0 | ticket | 1-5 | 8,469 | rejected: generated |

Drivers of real scores: waiting time (CSAT 4.48 if answered in 5 min -> 3.66 after 8 h) and delivery lateness (Olist
4.29 on time -> 1.68 at 8-14 days late).

## Follow-up (2026-10-25)

- **Licences re-checked**: Flipkart CSAT (Kaggle metadata `other`, no source, no terms) and USS (no LICENSE,
  READMEs/paper give no terms) are **still to verify**. A **fallback calibration** using only Olist (CC BY-NC-SA 4.0)
  and TripAdvisor (CC BY-NC 4.0) ships as `calibration_fallback.json`. It is weaker on support CSAT (qwen3.5 QWK 0.13
  vs 0.25 with the main map on the same 100 test rows); use it if the licence cannot be confirmed (SIMULATOR_README.md).
- **Delay-aware calibration**: mean score per waiting-time bucket now within 0.22 points of real on average (was
  0.42); 8 h+ waits 2.66 vs 3.74 real (was 2.04). Overall test QWK 0.35, Wasserstein 0.24. This matters for agent E:
  the old reward punished waiting about 3x more steeply than real customers.
- **Medi-Cal abandonment unit confirmed**: fraction 0-1 (source data dictionary), so 0.28 = 28% of queued calls.
  Terms: CHHS Terms of Use (free use with attribution).

## Still "to verify"

Flipkart CSAT licence; USS licence; Skytrax review terms; UserLM-8b's Llama 3.1 base terms;
SEE Lab data access. Details and owners: BLOCKERS.md.

## Needs team approval to download

Technion SEE Lab call-center data (access request to see@technion.ac.il). Nothing else is pending: every download used
was under 300 MB (largest: Twitter, 177 MB zip).
