# Photo check (vision) — integration in CallVerse

## In plain words
A customer can now attach a photo in the ShopNova or Atlas Help chat, or on Molka's website. A small vision model
(Qwen3-VL-2B with the CallVerse QLoRA adapter) says only **what the photo shows**: a cracked screen, a torn box,
a broken suitcase, a dirty room, nothing wrong, or "cannot tell". The text still says what the customer **wants**
(Intake). The two are joined by fixed rules (late fusion) before the router. The photo check never decides
anything. It can only supply the "photo proof" that rule R-DMG-01 already asked for, and the Coordinator still
checks every other rule.

## Flow
```
            CUSTOMER MESSAGE (text and / or one photo)
                  |                         |
                TEXT                      PHOTO
                  |                         |
        Intake (M3 + M4, unchanged)   callverse/vision/model.py
        reason, facts, priority       Qwen3-VL-2B + QLoRA adapter  (fallback: base model, same prompt)
                  |                   -> visual evidence JSON (6 keys), unverified
                  +------------+------------+
                               |
                 callverse/vision/fusion.py  (rules, no model)
                               |
                 Queue Router (unchanged) -> Agent A / B (+ one "Photo check (model, unverified)" line)
                               |
                 Coordinator (unchanged rules; R-DMG-01 reads proof_received from the CASE, set by the channel)
                               |
                 SLM reply writer (sees the decision only, never the photo)
```

## Fusion rules (`callverse/vision/fusion.py`)
| Situation | Reason used by the router | Why |
|---|---|---|
| Text has a clear reason | the text's reason, always | A photo cannot show intent. "Where is my order?" plus a broken phone stays `order_status`. |
| Text is unclear (`other`) + photo shows damage, ShopNova | `damaged_item` | ShopNova has a reason that *describes* the problem; it is not a wish. |
| Same at Atlas | stays `other` | Atlas has no "damage" reason, so an agent asks what the customer wants. |
| Photo only | as above, on a ticket with no text | Emotion and sentiment are **not measured**. They are set to neutral and marked `not_measured_photo_only`. |
| Photo proof (R-DMG-01) | `proof_received` = photo received **and** visible damage | A photo without visible damage, an unclear photo, or a failed check is not proof. |
| Text says damaged, photo shows none / photo unclear / not checked | `conflict` field, `requires_review` | Shown in the ticket steps for a human. |

Outcomes for a ShopNova damaged-item case:
- **Photo with damage**: the agent may propose; the Coordinator checks amount, client confirmation and finance limit as before.
- **Photo without visible damage, or the check failed**: escalated to a colleague. Nothing is paid, and the customer is never asked again for a photo they already sent.
- **No photo**: the customer is asked for one, as before.

## Model and fallback (`callverse/vision/model.py`, `config.yaml` → `vision:`)
- **Adapter:** `Ayachi7/CallVerse-Qwen3VL-2B-Vision-QLoRA` @ `40b84e5`, on base `Qwen/Qwen3-VL-2B-Instruct` @ `8964489`. Both revisions are pinned.
- **Fallback:** `backends: [qlora, base]`. If the adapter cannot load (missing, no network, wrong file), the base model runs with the same prompt. If both fail, `VisionError("model_unavailable")`: the channel marks the photo "not checked" and a human looks at it.
- **Invalid model text:** the answer becomes `unclear` and is never guessed. The output is normalised so it follows its own rules (for example, a damage type always means `visible_damage = true`).
- **File checks:** JPEG, PNG and WebP only, at most 5 MB and 40 Mpx, EXIF rotation applied, shrunk to 1024 px. The photo bytes are never stored; the ticket stores only `[Photo attached]` and the assessment.
- **Hardware:** GPU uses 4-bit NF4 if `bitsandbytes` is installed (as in training), else 16-bit. CPU uses float32.

## Why this adapter (benchmark, Kaggle T4, 25 held-out real photos, never used for any choice)
| System | Accuracy (95 % CI) | Macro-F1 | Damage recall | False alarm | Valid JSON | Median s / photo (T4) |
|---|---|---|---|---|---|---|
| Base, original short prompt | 0.00 | 0.00 | 0.00 (lenient 1.00) | — | 0 % | 5.6 |
| Base, improved prompt | 0.64 [0.44, 0.80] | 0.61 | 1.00 | 0.22 | 100 % | 3.7 |
| **Base + QLoRA adapter** | **0.84 [0.68, 0.96]** | **0.79** | **1.00** | 0.22 | **100 %** | 6.3 |

- **Paired comparison on the same photos:** adapter − improved prompt = **+0.20 [+0.08, +0.36]**, P(better) = 0.997.
- **Image check (8 val photos):** loss with the true photo 0.50 vs. swapped photos 1.07 after training; the gap grew from 0.38 (before) to 0.57, so the adapter reads the image.
- **Weak spot:** the `unclear` class (F1 0.00, n = 2), plus 2 intact items flagged as damaged.

## Real inference in this repository (no fake model)
`python -m scripts.vision_check --data <built dataset> --split test` runs the real adapter from Hugging Face on the
same 25 held-out photos. Results of the CPU run are in the PR description (CPU float32, much slower than the T4).

## Agent B prompt: decision needed (not changed)
Agent B's prompt is locked by a fingerprint test (`tests/test_routing_by_company.py`). It still says "Damaged: no
proposal, ask for a photo (R-DMG-01)". So today a real Agent B does **not** propose a refund after a photo, and the
case goes to a colleague (safe). To let it propose, the Brain must approve this one-line change and renew the
fingerprint:
```
Damaged: if the photo check note says "Photo proof for R-DMG-01 = yes", propose_refund citing R-DMG-01 (amount = paid
- refunded_total, the client must ask); otherwise no proposal, ask for a photo (R-DMG-01).
```
The end-to-end test of the "proof → Coordinator approves" path uses a fake Agent B that proposes.

## Files
- `callverse/vision/schema.py`, `model.py`, `fusion.py`: the photo check and the fusion rules.
- `callverse/channels/web_chat.py`: `send(..., image=bytes)`; `photo_check` step; `PHOTO_ERROR_REPLY`.
- `callverse/pipeline.py`:
  - the agent note gets the photo line;
  - `case.proof_received` comes from the fusion;
  - an `ask_proof` decision after a photo becomes an escalation.
- `callverse/web/vision.py` (Molka): same endpoint and error codes, now backed by the adapter. It returns the full assessment and keeps `damaged`.
- `apps/*/pages/*Help_chat.py`: the chat box accepts one photo (`st.chat_input(accept_file=True)`).
- Tests:
  - `tests/test_vision_integration.py`: 30 tests (fake model);
  - `scripts/vision_check.py`: the real-model check;
  - install: `pip install -r requirements-vision.txt`.
