# CallVerse Client Simulator kit (M1)

## Lean setup (TASK3, default)

- **Writer** (plays the customer): `gemma3:1b` in Ollama, prompted with the role card + 5 real example messages
  (`simulator/real_examples.json`). `ollama pull gemma3:1b`.
- **Scorer** (gives the 1-5 score): fine-tuned MiniLM, ONNX int8, CPU only (`score_mode: scorer`). Put
  `scorer_int8.onnx` and `tokenizer.json` in `models/scorer/` (not in git; get them with
  `kaggle kernels output <kaggle-user>/callverse-scorer-ft -p kaggle_out/scorer`, then copy from `kaggle_out/scorer/onnx/`).
  `pip install onnxruntime tokenizers`.
- **Ollama settings**: start Ollama with `OLLAMA_KV_CACHE_TYPE=q8_0` and `OLLAMA_FLASH_ATTENTION=1`; `num_ctx: 1024`
  (the longest test conversation needs 802 tokens). Call it at **`http://127.0.0.1:11434`, not `localhost`**: on Windows
  `localhost` adds about 2 s to every request (measured 2.5 s vs 0.28 s for the same call). With both: 0.47 s per message.
- `score_conversation` returns `score` (1-5), `expected_score` (continuous; use for agent E), `raw_score`, and a one-line
  `comment` written by the writer. `score_mode: llm` switches back to the previous LLM scoring.
- `scorer.calibration: quantile` is the **default**: the score distribution matches real customers (distance 0.06 vs
  0.55 with the plain setting) at a small accuracy cost (QWK 0.40 vs 0.43). Plain setting: `scorer.calibration: dev`.

**Why the quantile setting is the default.** The simulator's main job is not to guess one customer's score
exactly: that is M7's job. Its main job is to produce **realistic scores across thousands of simulated customers**,
because agent E learns from them as a reward. If the simulated scores bunch up in the middle (as a plain regression
model's do: distance 0.55 to the real distribution), agent E sees a reward with almost no 1s and few 5s, unlike real
customers. The quantile setting stretches the scores so they follow the real distribution (distance 0.06), and it keeps
almost all the per-customer accuracy (QWK 0.40 vs 0.43, MAE 0.80 vs 0.79 on the same 1,000 real CSAT rows; the 95%
intervals overlap). The plain setting stays available as `scorer.calibration: dev` (isotonic, best QWK).

### Final comparison (writer on the same 30 role cards; scorer on the same 1,000 real Flipkart CSAT test rows)

| Setup | GPU memory alone | GPU memory with qwen2.5:3b | Seconds per turn | Realism distance (lower = better) | Realism (0-6) | Stays in role (0-6) | Score MAE [95% CI] | Score QWK [95% CI] | Distance to real score distribution |
|---|---|---|---|---|---|---|---|---|---|
| **Before:** phi4-mini:3.8b writer + phi4-mini LLM scoring (main calibration) | 2510 MiB | 4534 MiB | 0.71 s | 0.177 (no examples) / 0.204 (5 examples) | 5 | 5 | 0.92 [0.84, 1.00] | 0.31 [0.24, 0.38] | 0.33 |
| **After:** gemma3:1b writer + MiniLM int8 CPU scorer (quantile setting) | 828 MiB (+0 GPU for the scorer) | 2854 MiB | 0.47 s + 9.88 ms per score (CPU) | 0.150 | 6 | 5 | 0.80 [0.72, 0.87] | 0.40 [0.33, 0.47] | 0.06 |

Seconds per turn and memory: same prompt, Ollama with KV q8_0 + flash attention, num_ctx 1024, requests to 127.0.0.1 (with 'localhost' Windows adds about 2 s per request; all earlier phases include that overhead). Memory with qwen2.5:3b = nvidia-smi increase with both models loaded.

Known limits of the lean setup: gemma3:1b returned an empty message 8.9% of the time before the clean-up step (2.2% after); the scorer was trained on e-commerce CSAT, Olist, TripAdvisor and USS, so Atlas support chats are scored with
the e-commerce CSAT tag (domain gap); it cannot predict USS annotator ratings.

---

## Writer clean-up (simulate_turn)

Small writers make small mistakes, so `simulate_turn` cleans every customer message:
- strips meta lines ("Here's my first message:", "As a customer, ...", stage directions like "(sighs)");
- retries once on an empty or assistant-style message ("how can I help", "as an AI");
- retries once if a FIRST message starts with the same three words as one of the last 50 first messages;
- adds light typo noise (swap two letters, drop apostrophes; for high-typo cards sometimes lowercase) when the role card
  asks for typos and the message has none: 25% of clean messages for medium cards, 40% for high cards (rates set from
  the real profile: 30% of real first messages have a spelling error).
Settings in `config.yaml` (`roleplay.retries`, `avoid_repeat_openers`, `typo_noise`, `typo_noise_prob`, `typo_lowercase_prob`).

Before/after for gemma3:1b on the same 30 role cards x 3 turns (same real examples and agent turns; `results/p9_writer_clean_summary.json`):

| | Realism distance (lower = better) | Empty replies | Breaks role | Test 1 realism / role (0-6) |
|---|---|---|---|---|
| before clean-up | 0.150 | 8.9% | 0.0% | 6 / 5 |
| after clean-up | 0.123 | 2.2% | 0.0% | 6 / 6 |

In the after run: 12 opener retries, 2 empty retries, 21 messages got typo noise,
2 of 96 turns stayed empty after the retry. The noise rates were checked on the same 30 cards they are
reported on (no separate dev set); a first version that added noise to every clean message overshot (realism 0.153).
Test 1 "after" was judged by Claude Code, not blind.

**Privacy:** real example messages and real agent replies are anonymised (handles, URLs, emails, phone numbers, IDs, and
person names: greetings like "Hi <first name>", clause ends like "Sorry about that, <first name>!", and first names from name lists).

## Previous setup (LLM scoring)

A small Python package that plays CallVerse customers through a local Ollama model and returns a 1-5
satisfaction score with a one-line comment, calibrated against real customer CSAT.

## Install and run

```sh
pip install requests pyyaml          # plus pytest for the tests
ollama pull qwen3.5:4b               # the top pick (see config.yaml); runner-up: ollama pull phi4-mini:3.8b
python -m pytest simulator/tests -q                  # mocked Ollama, no GPU needed
CALLVERSE_LIVE=1 python -m pytest simulator/tests/test_live.py -q   # optional, needs Ollama running
```

```python
from simulator import load_role_card, simulate_turn, score_conversation, sample_traffic

card = load_role_card("simulator/role_cards/shopnova/SN-01.yaml")
history = []
msg = simulate_turn(card, history)                 # first customer message
history += [{"role": "customer", "text": msg}, {"role": "agent", "text": "Could you confirm your order number?"}]
msg2 = simulate_turn(card, history)                # next customer message
result = score_conversation(card, history + [{"role": "customer", "text": msg2}])
# -> {"score": 4, "expected_score": 4.421, "raw_score": 4, "comment": "...", "valid_json": True, "breaks_role": False}
traffic = sample_traffic(100, "atlas", seed=1)     # reasons, hours, weekdays, give-up flags from real numbers
```

- `expected_score` is the calibrated continuous score (1.0-5.0): **use it for agent E's reward**. `score` is the
  same value rounded to 1-5. `raw_score` is the model's own answer.
- Add `wait_minutes: 45` to a role card (or set it before scoring) to tell the customer how long they waited.
  Real data shows waiting time is the strongest driver of CSAT, and with `wait_minutes` the kit applies the
  **delay-aware** calibration (per waiting-time bucket). Without it, the global map is used.
- With the fallback profile, add `days_late: 6` (or `"never"`) for delivery-lateness cards.

## Files

| File | What |
|---|---|
| `config.yaml` | model name, Ollama URL, temperatures, prompt versions |
| `prompts.py` | the exact role-play and scoring prompts measured in Phase 3 (`rp1`, `s2`) |
| `core.py` | `simulate_turn`, `score_conversation`, `load_role_card`, `sample_traffic` |
| `rubric.json` | rubric lines and 5 balanced few-shot examples, computed from the **train** split of the real CSAT data |
| `calibration.json` | main calibration per model: global map + delay-aware expected-score maps, fitted on real Flipkart CSAT (train rows; **licence to verify**) |
| `calibration_fallback.json`, `rubric_fallback.json` | fallback built only from confirmed-licence data (Olist CC BY-NC-SA 4.0; TripAdvisor CC BY-NC 4.0 distribution for Atlas, off by default) |
| `real_numbers.json` | reason mix, arrivals per hour and weekday, response times, give-up rate, real score distributions - each with its source |
| `role_cards/` | 15 ShopNova + 15 Atlas YAML cards (13 reuse PI Platforms golden scenarios, e.g. order 4512, booking BK-7731) |
| `tests/` | pytest with a mocked Ollama, plus one optional live test |

## Role-card format (YAML)

```yaml
id: SN-01
company: shopnova            # shopnova | atlas
reason: late_delivery        # one of the contact-reason labels
mood: frustrated but polite
typo_level: low              # low | medium | high
persona: {description: "A student in Germany who ordered a laptop.", language: English}
goal: "Your laptop has not arrived ... You want to know where it is and whether you get compensation."
facts: {order_id: 4512, due_on: 8 October, carrier: DHL}
patience_turns: 4            # for your conversation loop: give up after this many unhelpful agent turns
wait_minutes: 45             # optional: minutes the customer waited for the first answer
source_scenario: PI Platforms/scenarios/GS-SN-01.yaml   # optional
```

## Which model

`qwen3.5:4b` (Qwen, Apache 2.0, about 3.0 GB VRAM; it fits next to the agents' qwen2.5:3b on a 6 GB GPU, 5,733 MiB
used together, measured). Runner-up `phi4-mini:3.8b` (Phi, MIT, 2,957 MiB alone; 5,043 MiB together with qwen2.5:3b).
**If S1 (the agents' model family) is Qwen, set `model: phi4-mini:3.8b`** in `config.yaml`; `calibration.json`
already holds its map. Why these two: S2_simulator_llm.md.

## Which calibration profile (`scoring.calibration_profile` in config.yaml)

| Situation | Profile | Why |
|---|---|---|
| Flipkart CSAT licence confirmed (or internal, non-published use while it is being checked) | `main` (default) | Fitted on real **support-contact** CSAT; best match on test (QWK 0.35, Wasserstein 0.24, bucket-mean gap 0.22 with delay-aware) |
| Licence **cannot** be confirmed, or anything will be published | `fallback` | Uses only confirmed-licence data. Validated on Olist delivery ratings (qwen3.5 test QWK 0.46), but weaker on support-contact CSAT (QWK 0.13 vs 0.25 for `main` on the same 100 rows; scores too low, MAE 1.38 vs 0.78). Prefer qwen3.5 here: phi4-mini cannot do the Olist task (QWK 0.05) |

The USS licence does not affect the kit: USS was used only for the CONV test, not for either calibration.
Details: SCORE_CALIBRATION.md sections 3b and 7.

## Accuracy to expect against real scores (held-out test, see SCORE_CALIBRATION.md)

| | n | MAE | Spearman | QWK | Wasserstein to real distribution |
|---|---|---|---|---|---|
| qwen3.5:4b, main delay-aware calibration, real customer CSAT | 200 | 0.87 | 0.27 | 0.35 | 0.24 |
| qwen3.5:4b, main global map (no `wait_minutes`) | 200 | 0.81 | 0.30 | 0.33 | 0.26 |
| phi4-mini:3.8b, main delay-aware calibration | 200 | 0.88 | 0.17 | 0.20 | 0.23 |
| baseline "always 5" | 200 | 0.68 | n/a | 0.00 | 0.68 |
| baseline TF-IDF + LR trained on real CSAT | 200 | 0.55 | 0.36 | 0.42 | 0.44 |

Read it as: the **distribution** of simulated scores is close to the real one (69% fives, 13% ones in real CSAT),
and the score moves in the right direction with waiting time, but **per conversation** the score is only weakly
right (QWK about 0.3, 95% interval 0.16-0.49 for qwen3.5). Use it for averages over many simulated conversations
(agent E's reward, agent F's training signal), not as the truth for one conversation.

Speed: about 3 s per customer message on an RTX 3060 Laptop (3.06 s qwen3.5, 3.18 s phi4-mini; 120-token limit).

## Known limits

- Calibrated on Flipkart-style e-commerce CSAT; no real travel CSAT exists in our data, so Atlas scores use the same
  map (domain gap). Licence of the calibration data is "to verify" (BLOCKERS.md).
- Long waits: with the delay-aware map, mean score per waiting-time bucket is within 0.22 points of real on
  average (qwen3.5), but 8 h+ waits still score 2.66 vs 3.74 real (only 27 calibration rows in that bucket).
- Simulated first messages are cleaner than real ones: about 7-10% contain a spelling error vs 30% of real messages,
  and they have almost no emojis (0-3% vs 10% real) and few ALL-CAPS words (3% vs 14% real; Test 2, `results/p3_test2_realism.json`).
- `breaks_role` flags assistant phrases ("how can I help", "as an AI"); 0% in tests for qwen3.5, but check it.
- qwen3.x models need `think: false` (set automatically by `core.py`), otherwise replies come back empty.

