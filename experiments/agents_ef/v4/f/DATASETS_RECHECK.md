# Agent F v4 — dataset recheck (F3, 2026-10-26)

Rules followed: no agreement accepted, no login, no access restriction bypassed. Only public pages and APIs read.
V3 verdicts (`v3/f/DATASETS.md`) are kept unless a row below changes them.

## 1. What changed since V3

| Dataset | V3 said | v4 finding (source) | Consequence |
|---|---|---|---|
| **DCH-2 / DialEval-2** | "real helpdesk dialogues with customer satisfaction labels … the only reachable candidate that could pass the gate" (`v3/deliverables/10_AGENT_F_M7_SCOPE.md` §5) | The S-score is "Customer Satisfaction of the dialogue (not of the product/service or the company)", on a scale of −2..2, **annotated by "19 Chinese students"** for train/dev. The English side is "manually translated from the Chinese dataset". 4,390 dialogues per language. (https://dialeval-2.github.io/DCH-2/) | The labels are **annotator judgements**, not customer ratings. DCH-2 would **still fail** the gate's `label_type = genuine_customer_rating`. The V3 sentence is corrected here. DCH-2 stays valuable as a closer **domain** (customer helpdesk) for the KPI use. |
| DCH-2 access | "needs a signed agreement" | Access is a Google-form user agreement (https://forms.gle/dk3wjqFTEF9k8SAe6). The terms (https://dialeval-2.github.io/DCH-2/terms): "only for researchers who wish to use the dialogues for non-commercial research and/or educational purposes"; colleagues only if "they first agree to be bound by these terms"; organizers "do not own the copyright of the dialogues"; annotations under CC BY 4.0; the employer is bound if for-profit. Contact: dialeval2org@list.waseda.jp. Cost: none stated. | **BLOCKED for this session**: accepting it is a legal act for Yassine / the supervisor (university, non-commercial: it looks eligible). **Not accepted.** |
| "MLchart customer support transcripts" (MLC-0802) | — | Catalog page: "Anonymised customer support conversations", a "Post-contact satisfaction score, in the surveyed subset", EN. Access is "Request this dataset" / "How to order". Licence, provenance (real or synthetic) and who gives the score are not stated. (https://mlchart.com/datasets/customer-support-transcripts/) | **NOT ACCESSED**: commercial order, provenance unknown. Not a candidate without a purchase decision. |
| MAIA bilingual support dialogues (arXiv 2311.13910) | — | Annotations for "emotion and conversational quality" of "bilingual customer support conversations". No customer satisfaction label; the release location is not stated on the abstract page. | **NOT A SATISFACTION LABEL**. It could be a quality-annotation reference only. |
| arXiv 2607.11026 "Dimensionality in Satisfaction Ratings" | — | About 9,000 support conversations of a consumer-goods firm, with satisfaction ratings "customers gave themselves". The data are not released (abstract page). | **NOT AVAILABLE**, but useful evidence: real CSAT exists only inside companies. That is why CallVerse needs its own contract (`contracts/reviews_contract.md`). |
| Hugging Face hub search (`csat`, `customer-satisfaction`, `satisfaction dialogue`, `customer support satisfaction`; API, no login) | — | The results are Korean exam "CSAT" sets, transport / airline / restaurant review sets, a Santander tabular set, and the two Flipkart CSAT mirrors already seen in V3. No support **dialogue** with customer ratings. | Nothing new to use. |

## 2. Unchanged

- **USS**: still the primary benchmark. Its labels are annotator judgements (EN α 0.20–0.28, ZH α 0.52).
- **Amazon EN/FR**: auxiliary. These are product stars, not support satisfaction. It is the only French evidence, and only for the e5 family.
- **Saif7800**: rejected (synthetic labels).
- **Flipkart CSAT**: no dialogue text.
- **Kaggle sets**: need a login; not accessed.

## 3. Real prototype traces (searched for an unscripted test set)

- 13 trace files were found in `/home/user/CallVerse/traces`, `/home/user/CallVerse-integration/traces` and the platform scratch folders.
- **None contains a closed conversation**: 0 `pipeline_done` lines, and no `llm_call` lines.
- So the only closed conversations available are the scripted M7 corpus (240).

## 4. Conclusion

- **No accessible dataset has genuine customer ratings of support dialogues.** The gate's label type can only be met by CallVerse's own reviews (the contract) or by a company dataset under agreement.
- An annotated CallVerse set (`ANNOTATION_PROTOCOL.md`) can validate the **domain** and the **KPI use**. It cannot validate E's reward without a Brain decision to accept annotator labels there.
