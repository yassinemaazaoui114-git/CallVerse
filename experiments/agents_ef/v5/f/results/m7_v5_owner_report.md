# M7 v5 — owner report material (SCRIPTED corpus: describes the scripted mix, not real operation)

| Flag | dev (n=120) | held-out (n=120) | 95% CI dev / held-out | Difference credible? | Example evidence | Suggested human action |
|---|---|---|---|---|---|---|
| agent_answered_without_tools | 5 | 6 | [0.0179, 0.0938] / [0.0231, 0.1048] | no (CIs overlap) | dev-0039.jsonl:13, dev-0044.jsonl:13 | agent answered from memory: check the prompt / tool forcing |
| cited_missing_rule | 1 | 1 | [0.0015, 0.0457] / [0.0015, 0.0457] | no (CIs overlap) | dev-0095.jsonl:31, test-0031.jsonl:27 | remove the old rule id from the agent prompts |
| claim_false | 4 | 4 | [0.013, 0.0826] / [0.013, 0.0826] | no (CIs overlap) | dev-0005.jsonl:27, dev-0005.jsonl:27 | read the case: an agent stated a fact contradicting the platform data |
| escalated | 9 | 6 | [0.04, 0.1364] / [0.0231, 0.1048] | no (CIs overlap) | dev-0005.jsonl:104, dev-0015.jsonl:20 | check the escalation reasons (agent errors vs genuine edge cases) |
| missed_entitlement | 0 | 1 | [-0.0, 0.031] / [0.0015, 0.0457] | no (CIs overlap) | test-0031.jsonl:38 | read the case: a due refund was not given |
| pipeline_error | 5 | 2 | [0.0179, 0.0938] / [0.0046, 0.0587] | no (CIs overlap) | dev-0015.jsonl:12, dev-0022.jsonl:13 | check the LLM provider and error handling |
| proposal_malformed | 1 | 1 | [0.0015, 0.0457] / [0.0015, 0.0457] | no (CIs overlap) | dev-0095.jsonl:31, test-0031.jsonl:27 | check the agent's proposal format |
| reply_language_mismatch | 29 | 23 | [0.1739, 0.3255] / [0.1312, 0.2712] | no (CIs overlap) | dev-0000.jsonl:39, dev-0001.jsonl:39 | add French reply templates / make the SLM answer in the client's language |
| rule_not_searched | 1 | 2 | [0.0015, 0.0457] / [0.0046, 0.0587] | no (CIs overlap) | dev-0033.jsonl:34, test-0023.jsonl:34 | agent cites rules without searching: check the agent prompt |
| sent_back | 7 | 4 | [0.0285, 0.1155] / [0.013, 0.0826] | no (CIs overlap) | dev-0005.jsonl:40, dev-0016.jsonl:42 | read the send-back reasons; repeated ones mean the agent misreads a rule |
| slm_fallback_template | 120 | 120 | [0.969, 1.0] / [0.969, 1.0] | no (CIs overlap) | dev-0000.jsonl:39, dev-0001.jsonl:39 | check why the SLM gives no passing reply (here: SLM offline during the corpus build) |

Trend over time: NOT AVAILABLE (all scripted conversations carry the same simulated date 2026-10-09); dev vs held-out is the only comparison and it is a batch difference, not a trend.
