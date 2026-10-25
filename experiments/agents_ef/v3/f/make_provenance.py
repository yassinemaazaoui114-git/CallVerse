"""Writes v3/f/data_provenance.json. USS numbers are read from results/uss_stats.json (made by uss_data.py);
the other entries record what was checked by hand on 2026-10-25 (file listings / small samples, see DATASETS.md)."""
import json
from pathlib import Path

H = Path(__file__).resolve().parent
uss = json.loads((H / "results" / "uss_stats.json").read_text())
prov = {
 "checked_on": "2026-10-25", "checked_by": "Worker F (Claude Code, cloud sandbox, CPU only)",
 "local_callverse_datasets": "BLOCKED: no access to local CallVerse datasets (user's Windows PC not reachable "
                             "from this sandbox; paths like C:\\Users\\semah\\... not accessible)",
 "datasets": {
  "A_USS": {
   "name": "USS - User Satisfaction Simulation (Sun et al., SIGIR 2021, arXiv 2105.03748)",
   "urls": {"original_used": "https://github.com/sunnweiwei/user-satisfaction-simulation (dataset/*.txt, branch master, raw files)",
            "hf_mirror": "https://huggingface.co/datasets/akomma/uss-ratings-dataset (sha 0d89e2f93b93c57564269a69c53d34143dfe4ea4)"},
   "licence": "GitHub repo: NO LICENSE file found (raw LICENSE -> 404). HF mirror card declares MIT (stated by the "
              "mirror uploader, not by the authors). Underlying corpora have their own terms (SGD CC-BY-SA-4.0, "
              "MultiWOZ MIT, ReDial CC-BY-4.0, CCPE CC-BY-SA-4.0, JDDC research-only per JD.com). Verdict: academic "
              "research use with citation; do not redistribute raw text.",
   "why_original_not_mirror": "the HF mirror is parquet (no parquet reader in the venv) and has only 4 EN sub-datasets; "
                              "the original TXT has per-annotator ratings for all 5 sub-datasets incl. JDDC. The mirror "
                              "parquet was downloaded (sha256 b1337c9c00617e7df4f72cad1f3e99573badf5bea30e18a560fdfbe6b58c2b00, "
                              "2.3 MB) but its rows were NOT VERIFIED (not parsed); its card reports 3,500 dialogs / 34,358 turns.",
   "size_bytes_raw": "SGD 1,838,324; MWOZ 2,106,294; ReDial 1,123,392; CCPE 1,182,562; JDDC 6,568,777",
   "schema": "TXT, one utterance per line: ROLE \\t text \\t action \\t ratings 'a,b,c' (USER lines) [\\t explanation]; "
             "dialogues separated by blank lines; last line 'USER \\t OVERALL \\t \\t r1,r2,..' = dialogue-level rating.",
   "label_semantics": "1-5 user satisfaction judged by crowd/expert annotators reading the dialogue (third-party "
                      "judgement, NOT self-reported by the real user). Turn level: satisfaction at each user turn "
                      "(with the preceding system response). Dialogue level (OVERALL): satisfaction with the whole dialogue.",
   "agent_f_target": "mean of the annotators' OVERALL ratings; predicted after the dialogue ends from the full dialogue text",
   "languages": {"en": ["SGD", "MWOZ", "ReDial", "CCPE"], "zh": ["JDDC"]},
   "domain": "SGD/MWOZ: task-oriented assistants (booking, travel, weather...); ReDial: movie recommendation; "
             "CCPE: preference elicitation (movies); JDDC: REAL e-commerce customer service chats (JD.com) - closest to ShopNova.",
   "grouping_key": "(sub-dataset, dialogue index in file); one example = one dialogue, so turns never cross splits",
   "per_subdataset": uss["files"],
   "split": {"rule": uss["split_rule"], "counts": uss["split_counts"], "sha256": uss["split_sha256"]},
   "duplicates": "exact duplicate dialogue texts: JDDC 28 (dropped, first kept), others 0",
   "inter_annotator": "3-7 annotators per dialogue (EN), exactly 3 (JDDC). Krippendorff alpha (interval) on OVERALL: "
                      "SGD 0.225, MWOZ 0.199, ReDial 0.28, CCPE 0.202, JDDC 0.524 (see per_subdataset). EN labels are "
                      "concentrated on 3 (std of the mean rating 0.35-0.45) and noisy.",
   "verdict": "USABLE as the PRIMARY public benchmark for dialogue-level satisfaction (EN and ZH reported separately). "
              "Caveats: annotator (not customer) judgements; EN sub-datasets are not customer support; low EN agreement "
              "limits achievable accuracy; JDDC is genuine e-commerce support but Chinese (no FR)."},
  "B_DialEval2_DCH2": {
   "name": "DialEval-2 / DCH-2 (NTCIR-15 Dialogue Evaluation, Customer Helpdesk dialogues, Chinese + English translation)",
   "url": "https://dialeval-2.github.io/DCH-2/",
   "licence": "requires a signed user agreement",
   "accessed": False, "reason": "agreement required -> NOT accessed (rule: never accept agreements)",
   "label_semantics_from_public_description": "dialogue-level quality scores (task accomplishment, customer satisfaction, "
                                               "effectiveness) and nugget annotations by multiple annotators - NOT VERIFIED here",
   "verdict": "HIGH-VALUE FUTURE dataset (real helpdesk dialogues, satisfaction-type labels). Needs Yassine/teacher to sign the agreement."},
  "C_Amazon_EN_FR": {
   "name": "Amazon Multilingual Reviews (Keung et al. 2020), MTEB mirror", "url": "https://huggingface.co/datasets/mteb/amazon_reviews_multi",
   "licence": "Amazon non-commercial research licence (as recorded in v2)",
   "rows_used": {"train": 1200, "val": 400, "test": 399}, "languages": ["en", "fr"],
   "label_semantics": "star rating 1-5 the customer gave a PRODUCT (self-reported), balanced by the corpus authors",
   "reuse": "existing subset (scratchpad/data_amazon/subset_enfr) and v2 results (results/f_v2_enfr/*.json); not rebuilt",
   "verdict": "AUXILIARY only (product satisfaction, single review text, not a support dialogue). Never merged with USS numbers."},
  "D_Saif7800_customer_qa": {
   "name": "Saif7800/customer_qa_dataset", "url": "https://huggingface.co/datasets/Saif7800/customer_qa_dataset",
   "revision": "b2dc281b63c6e6fea10c531cd71680498ca3e7fd", "licence": "CC0-1.0 (card)",
   "size": "train 1,365,546,421 B (450,724 rows), validation 79,667,470 B (24,988), test 79,653,461 B (24,988) - too big; "
           "only the first 3,000,000 bytes of validation_complete.jsonl were fetched (939 rows parsed)",
   "schema": "29 columns incl. conversation[{role,text}], language, domain, sentiment, resolution, csat (1-5), quality_score",
   "observations_on_939_rows": {"source": "llm_generated_v6_augmented 932, llm_generated_v6 5, llm_generated_v5 2",
       "csat_vs_sentiment": "urgent->3 (208/208), confused->3 (208/208), frustrated->2 (109) or 3 (58), neutral->4 (193) or 3 (13), "
                            "positive->4 (80) or 5 (70): csat is (almost) a deterministic function of the sentiment tag",
       "csat_counts": {"2": 109, "3": 487, "4": 273, "5": 70},
       "resolution_counts": {"unresolved": 663, "escalated": 107, "resolved": 83, "follow_up_needed": 47, "refunded": 39},
       "languages": {"en": 802, "fr": 52, "es": 50, "de": 35}},
   "verdict": "SYNTHETIC (LLM-generated), labels rule-derived from a sentiment tag; 'unresolved' conversations get csat 4-5 often. "
              "NOT USED for training or evaluation. At most a clearly-labelled synthetic smoke test (format checks)."},
  "E_candidates_searched": [
   {"name": "sharmila122125/customer-support-csat (Flipkart customer-service CSAT, mirror of a Kaggle dataset)",
    "url": "https://huggingface.co/datasets/sharmila122125/customer-support-csat", "licence": "apache-2.0 on mirror; "
    "upstream Kaggle licence NOT VERIFIED", "rows": 85907, "with_customer_remarks": 28742,
    "csat_counts": {"1": 11230, "2": 1283, "3": 2558, "4": 11219, "5": 59617},
    "text": "only a short survey remark (median 19 chars, e.g. 'Good'), written WITH the score; no dialogue transcript; "
            "operational metadata (channel, category, response time, agent tenure, shift)",
    "verdict": "CANDIDATE (real-looking operational CSAT, e-commerce support) for a metadata-based or remark-based auxiliary "
               "task; NOT benchmarked (no dialogue text; remark leaks the score; upstream licence unverified)."},
   {"name": "rootfs/user-satisfaction-dataset", "url": "https://huggingface.co/datasets/rootfs/user-satisfaction-dataset",
    "verdict": "NOT a satisfaction rating: 4 balanced intent-like classes (SAT / NEED_CLARIFICATION / WRONG_ANSWER / "
               "WANT_DIFFERENT) on single follow-up messages; rejected for Agent F."},
   {"name": "Kaggle 'Customer Support Ticket Dataset' (CSAT column)", "verdict": "NOT ACCESSED (Kaggle needs login); "
    "widely reported as synthetic -> would not be used as ground truth"},
   {"name": "LEGO corpus (Let's Go bus information, interaction quality 1-5 per exchange, Schmitt et al. 2012)",
    "verdict": "NOT ACCESSED in this round; spoken-dialogue IQ labels by experts; possible future auxiliary set"},
   {"name": "HF searches 'csat', 'customer satisfaction', 'user satisfaction', 'dialogue quality', 'interaction quality'",
    "verdict": "no other public dataset with genuine dialogue-level satisfaction labels found (other hits: exam datasets "
               "named CSAT, tabular surveys, review sites)"}]}}
(H / "data_provenance.json").write_text(json.dumps(prov, indent=1, ensure_ascii=False))
print("written", H / "data_provenance.json")
