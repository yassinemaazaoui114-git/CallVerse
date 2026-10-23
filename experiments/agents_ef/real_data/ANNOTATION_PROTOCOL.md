# Satisfaction annotation protocol (Agent F ground truth)

**Why this exists.** Most customer-support message datasets have intents or scenarios, but no satisfaction rating.
An intent ("refund_request") says *what* the customer wants, not *how satisfied* they are. So Agent F cannot be evaluated on real text until someone labels satisfaction.

This protocol produces a small, trustworthy label set.

## 1. What is labelled

**Unit:** one conversation, the whole thread.
- If the dataset only has single messages, label the customer's **last** message together with the agent reply before it, if there is one.

**Question:** "At the end of this exchange, how satisfied is the customer likely to be?"

| Score | Meaning | Typical signs |
|---|---|---|
| 1 | Very unsatisfied | anger, threat to leave or complain, problem clearly not solved |
| 2 | Unsatisfied | frustration, repeated contact, partial or wrong answer |
| 3 | Neutral / unclear | factual exchange, no emotional signal, outcome unknown |
| 4 | Satisfied | problem solved or clear next step, polite thanks |
| 5 | Very satisfied | explicit praise, fast resolution, warm thanks |

**Extra fields**
- `resolved`: yes / no / unclear.
- `language`: en / fr / mixed.
- `confidence`: low / medium / high.

**Rules**
- Label from the text only. Do not use the intent label, the order data, or the system's prediction.
- When the text gives no signal, use 3 with low confidence. Do not guess.

## 2. Sample

- **Size:** 300 conversations from the stratified subset made by `real_data/prepare_subset.py`.
  - 210 English, 90 French: the same 70/30 mix as the authorised 5,600 / 2,400 subset.
  - Spread over intents, with at least 15 per intent where possible.
- **Where they come from:**
  - VAL is used to tune and choose models;
  - TEST is used to score them;
  - TRAIN may be labelled later for fine-tuning.
  - Never move a conversation between splits after labelling.
- **Order:** labellers see the conversations in a random order, never grouped by intent.

## 3. Annotators and agreement

- **Annotators:** two per conversation, working independently. French items need a fluent French speaker.
- **Calibration round:**
  - both annotators label the same 30 conversations;
  - they discuss the disagreements and update the examples in this file;
  - those 30 are then **excluded** from TEST.
- **Agreement measures:**
  - quadratic-weighted Cohen's kappa on the 1–5 scale;
  - plain kappa on the 3 classes (unhappy 1–2 / neutral 3 / happy 4–5).
- **Thresholds:**
  - target kappa ≥ 0.6;
  - below 0.4: fix the guidelines and relabel the batch.
- **Final label:**
  - the mean of the two scores;
  - a third annotator decides when the two differ by 2 or more.

## 4. Evaluation of Agent F on these labels

**Metrics, all on TEST:**
- MAE;
- RMSE;
- macro-F1 on the 3 classes;
- Spearman correlation;
- a confusion matrix.

**Reported:**
- per language (EN / FR);
- per intent;
- against the human ceiling: the annotators' own MAE against each other.

**Baselines, always reported:**
- predict the TRAIN mean;
- meta features only;
- TF-IDF + Ridge.
- TinyBERT counts as useful only if it beats these by more than the seed spread (3 seeds).

**French note.** TinyBERT-General is English-only. On French text, report it **separately**. If it fails there, test a small multilingual encoder before concluding. Candidate: `paraphrase-multilingual-MiniLM-L12-v2`, 118M parameters, which still fits 6 GB VRAM. That model is RESEARCHED only, not tested here.

## 5. Privacy and storage

- Real conversations and labels stay **outside git**, in the folder set by `CALLVERSE_DATA_DIR`.
- Only aggregate numbers go into the repository.
- Annotators get only the subset they label, with names, emails, phone numbers and order IDs masked.
- Use only the separately authorised 8,000-message subset. Do not draw from the full 144,794-message collection.
