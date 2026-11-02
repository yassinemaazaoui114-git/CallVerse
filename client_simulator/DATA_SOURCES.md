# Data sources (TASK3: lean simulator)

Every evaluation uses **held-out REAL data**; nothing was trained on a test split. "Real" = written/scored by real
people; "generated" = produced by a model or template.

| Source | Real / generated | Who wrote the text / gave the score | Licence | Used for | Test set used |
|---|---|---|---|---|---|
| Customer Support on Twitter (Kaggle thoughtvector) | real | customers (tweets) | CC BY-NC-SA 4.0 | writer fine-tune (job A): 2,400 first messages + 1,600 follow-ups; prompt examples; realism profile | 10% of threads held out by hash (24,838 messages), never in training |
| Twitter US Airline Sentiment (Kaggle crowdflower) | real | customers; sentiment labels by annotators | CC BY-NC-SA 4.0 | writer fine-tune: 1,000 first messages | held-out threads (by tweet id hash) |
| eCommerce Customer Service Satisfaction (Kaggle ddosad) | real scores; identifiers replaced with Faker values by the uploader | customer CSAT 1-5 + remark | "other" on Kaggle, no terms stated; **team-approved for this project** (2026-10-26) | scorer train (train split), choice on dev | 1,000-row test sample (same rows as the phi4-mini baseline) |
| Olist Brazilian E-Commerce reviews (Kaggle olistbr) | real | customer review score 1-5 + Portuguese comment (kept as written, not translated) | CC BY-NC-SA 4.0 | scorer train, choice on dev | 500 test rows (same rows as the phi4-mini fallback run) |
| Trip Advisor Hotel Reviews (Kaggle andrewmvd; Alam et al. 2016) | real | customer rating 1-5 + review | CC BY-NC 4.0 | scorer train, choice on dev | 500 test rows (seed 42 split 70/15/15) |
| USS MultiWOZ + SGD travel dialogues (GitHub sunnweiwei) | real ratings of role-played dialogues | annotators (40 invited, 3 per dialogue) | no licence file; **team-approved for this project** (2026-10-26) | scorer train, choice on dev | full test split, 186 dialogues (fewer than 300: the whole split) |
| PI Platforms scenarios (team mock platforms) | generated (team-written) | team | team-internal | role cards for writer tests | - |
| Writer role cards for fine-tuning (mood, typo level) | derived by rules from the real message (caps/!/swear words -> angry; spelling errors/lowercase -> typo level) | rules | - | labels only; the target text is always the real message | - |

Anonymisation: @handles, URLs, emails, phone numbers, long IDs and agent sign-offs replaced with placeholders before
any training or upload. The Kaggle dataset `callverse-memberb-train` is **private** and holds only train + dev rows.
No raw or processed data is in git (`.gitignore`: data/, kaggle_upload/, kaggle_out/). The MiniLM scorer weights are in
git (`models/scorer/`); other model weights are not.

Data use: the team approved every dataset above for this project (2026-10-26). The Licence column keeps what each source states.
