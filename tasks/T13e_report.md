# T13e report — Small SLM test: which small model should be the reply writer's base for LoRA/QLoRA?

## 1. In plain words
I tested 4 small local models as the reply writer against today's qwen2.5:3b. Each model wrote the same 14 practice
replies with today's settings and today's rule check. **qwen2.5:1.5b** did as well as qwen2.5:3b: 14/14 replies passed
on the first try, nothing invented, no template needed. It uses about half the GPU memory (1.2 GB instead of 2.2 GB)
and has the open Apache 2.0 licence. The two 1-billion models (gemma3:1b, llama3.2:1b) often copied a line of their
instructions into the reply, so the check had to reject it. qwen3:1.7b was good (13/14) but is above the 1.5 GB limit.
Nothing was changed in the project; `config.yaml` still says qwen2.5:3b. Yassine decides.

## 2. Done
- Branch `feature/t13e-small-slm` from `origin/main` c2b222a; first commit 1742d16 (task file, NEXT.md IN PROGRESS).
- Ollama 0.40.12 answered. Pulled the 4 official tags: `qwen2.5:1.5b`, `qwen3:1.7b`, `gemma3:1b`, `llama3.2:1b`
  (all existed, no substitute). Baseline `qwen2.5:3b` was already installed.
- **qwen3:1.7b thinking off**, proved by a one-off local call ("17 + 25 = ?"):
  default → 479 completion tokens, 1,318 reasoning characters; `reasoning_effort: "none"` → **3 tokens, 0 reasoning
  characters**. In the runs: 0 replies contain `<think>`, largest completion 58 tokens. (Without thinking it answered
  "32", a hint that small models are weak at arithmetic; the reply writer copies numbers and does not compute them.)
- Ran each model on its own (`--all dev` 8 decisions + `--all test` = spent v1 set, 6 decisions), temperature 0,
  seed 42, today's rule check. Before each model: free RAM checked, model preloaded (as the pipeline's warm-up does,
  so load time is not counted in the first reply). After: `ollama stop`. **The held-out v2 set was not run.**
- qwen3:1.7b was run through a tiny wrapper `out/t13e/run_slm_opts.py` (git-ignored). It adds
  `options: {reasoning_effort: none}` to the loaded config **in memory**, the same way `run_slm.py --model` changes
  the model name, then calls `run_slm.main()`. The other 4 models used `scripts/run_slm.py` directly.
  Other one-off helpers in `out/t13e/` (git-ignored): `run_model.sh` (one model's runs), `stats.py` (numbers below).
- No change to `config.yaml`, the SLM prompt, the rule check, templates or any code.

## 3. Evidence

### Main table (dev 8 + v1 6 = 14 decisions per model)
| Model | Size (as loaded, `ollama ps`) | First-try pass | Needed a retry | Template fallback | Invented numbers/facts (failed attempts) | s per reply avg / max | GPU memory used | Licence | LoRA/QLoRA support |
|---|---|---|---|---|---|---|---|---|---|
| qwen2.5:3b (today) | 2.2 GB | **14/14 = 100%** | 0% | 0% | 0 | 2.75 / 3.24 | 2,165 MiB | Qwen Research Licence (non-commercial) | Unsloth yes ([unsloth/Qwen2.5-3B-Instruct](https://huggingface.co/unsloth/Qwen2.5-3B-Instruct)) · PEFT yes ([Qwen/Qwen2.5-3B-Instruct](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct)) |
| **qwen2.5:1.5b** | **1.2 GB** | **14/14 = 100%** | 0% | 0% | **0** | **2.59 / 3.08** | 1,217 MiB | **Apache 2.0** | Unsloth yes ([unsloth/Qwen2.5-1.5B-Instruct](https://huggingface.co/unsloth/Qwen2.5-1.5B-Instruct)) · PEFT yes ([Qwen/Qwen2.5-1.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct)) |
| qwen3:1.7b (thinking off) | 1.7 GB | 13/14 = 92.9% | 0% | 1/14 = 7.1% | 2 (one decision, 2 attempts: "refund is processed") | 2.86 / 5.36 | 1,737 MiB | Apache 2.0 | Unsloth yes ([unsloth/Qwen3-1.7B](https://huggingface.co/unsloth/Qwen3-1.7B)) · PEFT yes ([Qwen/Qwen3-1.7B](https://huggingface.co/Qwen/Qwen3-1.7B)) |
| gemma3:1b | 0.9 GB (879 MB) | 9/14 = 64.3% | 1/14 = 7.1% | 4/14 = 28.6% | 5 (numbers) + 1 false "we've made the refund" (caught by another rule) | 4.02 / 6.91 | 955 MiB | Gemma Terms of Use | Unsloth yes ([unsloth/gemma-3-1b-it](https://huggingface.co/unsloth/gemma-3-1b-it)) · PEFT yes ([google/gemma-3-1b-it](https://huggingface.co/google/gemma-3-1b-it)) |
| llama3.2:1b | 1.5 GB | 11/14 = 78.6% | 2/14 = 14.3% | 1/14 = 7.1% | 4 (numbers) | 3.15 / 5.80 | 1,543 MiB | Llama 3.2 Community Licence | Unsloth yes ([unsloth/Llama-3.2-1B-Instruct](https://huggingface.co/unsloth/Llama-3.2-1B-Instruct)) · PEFT yes ([meta-llama/Llama-3.2-1B-Instruct](https://huggingface.co/meta-llama/Llama-3.2-1B-Instruct)) |

- Retry and template are counted per decision. A decision is "template" when both SLM attempts failed the check.
  Every **final** reply of every model passed the check (the template is the safety net).
- "Invented numbers/facts" = SLM attempts that the check rejected for numbers not in the decision, a refund promise
  that was not approved, or an invented name. Rejected attempts never reach the client.
- GPU memory = `nvidia-smi` while only that model was loaded (RTX 4050 Laptop, 6,141 MiB; nothing else on the GPU).
- Licences from `ollama show --license`. The 10 Hugging Face pages linked above answered HTTP 200; the PEFT docs
  (https://huggingface.co/docs/peft) work with any of these Hugging Face models.

### Per set
| Model | dev (8): first try · retry · template · avg s | v1 (6): first try · retry · template · avg s |
|---|---|---|
| qwen2.5:3b | 8 · 0 · 0 · 2.80 | 6 · 0 · 0 · 2.68 |
| qwen2.5:1.5b | 8 · 0 · 0 · 2.55 | 6 · 0 · 0 · 2.64 |
| qwen3:1.7b | 8 · 0 · 0 · 2.66 | 5 · 0 · 1 (s05) · 3.12 |
| gemma3:1b | 4 · 1 (d03) · 3 (d04, d06, d07) · 4.61 | 5 · 0 · 1 (s04) · 3.24 |
| llama3.2:1b | 7 · 0 · 1 (d06) · 2.91 | 4 · 2 (s01, s04) · 0 · 3.46 |

### Why the small models failed (from the traces)
- **gemma3:1b and llama3.2:1b copy the style instruction into the reply**, e.g. gemma d03 "Hello, length: Very short:
  2 or 3 sentences, at most 45 words. We have received your order 4513…". llama d06 does the same with "length:
  Clear: 3 to 5 sentences, at most 80 words". The numbers 2, 3, 45 / 3, 5, 80 are what the check caught. 7 of the
  9 "numbers" failures are this.
- gemma3:1b d07 (escalate, 4506): "We've made the refund for order 4506, and it's now being processed. We'll be in
  touch shortly". That is a false refund claim. It was rejected for "shortly" / "be in touch", then went to template.
- qwen3:1.7b s05 (ask_proof): "Please provide this evidence before any replacement or refund is processed. Ask the
  client for a photo…". The check read "refund is processed" as a promise (a strict reading of a conditional
  sentence), but the reply also talks about "the client" in the third person, so the template was the right call.
- llama3.2:1b d03 passed but wrote "The next step is: You can follow…", another label copied from the prompt.

### 5 example replies per model (same decisions: d01 approve, d03 info, d05 ask_proof, d06 layer3, d08 ask_user)
**qwen2.5:3b**
- d01: Dear customer, order 5042. Your refund of 74.90 TND is approved. The money goes back to the card you paid with.
- d03: Hello, order 4513. The parcel has already shipped on time according to the carrier. You can follow the parcel with the Aramex tracking number in your account.
- d05: Dear customer, please accept our apologies for the trouble. Order 4507. Please send us a photo of the damaged item and its box. Reply to this message with the photo so we can review your case.
- d06: Hello, order 5017. Refunds above 300 TND need approval from our finance team. The refund is not approved yet. Our finance team reviews the request and we reply to you with their decision.
- d08: Dear customer, order 4514. Could you tell us if you want to keep cash on delivery or pay by card?

**qwen2.5:1.5b**
- d01: Dear customer, about your order 5042: your refund of 74.90 TND is approved. The money goes back to the card you paid with. Thank you for your understanding.
- d03: Hello, your order 4513 has been shipped and is on time. You can follow the parcel with the Aramex tracking number in your account.
- d05: Dear customer, please accept our apologies for the trouble. About your order 4507: please send us a photo of the damaged item and its box. Reply to this message with the photo so we can review your case.
- d06: Hello, About your order 5017: refunds above 300 TND need approval from our finance team. The refund is not approved yet. Our finance team reviews the request and we reply to you with their decision.
- d08: Dear customer, order 4514 is currently processing. Could you tell us if you want to keep cash on delivery or pay by card?

**qwen3:1.7b**
- d01: Dear customer, your refund of 74.90 TND is approved. The money goes back to the card you paid with. Order 5042 is stuck at depot.
- d03: Hello, order 4513. The parcel has been shipped and is on track. You can follow the parcel with the Aramex tracking number in your account.
- d05: Dear customer, please accept our apologies for the trouble. Order 4507. Please send us a photo of the damaged item and its box. Reply to this message with the photo so we can review your case.
- d06: Hello, order 5017. Refunds above 300 TND need approval from our finance team. The refund is not approved yet. Our finance team reviews the request and we reply to you with their decision.
- d08: Dear customer, order 4514 is processing. Could you tell us if you want to keep cash on delivery or pay by card?

**gemma3:1b**
- d01: Dear customer, we are pleased to inform you that your request for order 5042 has been approved. Your refund of 74.90 TND is approved. This refund is a result of the parcel being stuck at the depot. The money goes back to the card you paid with. The refund process has been initiated.
- d03 (attempt 2): Hello, order 4513 has been shipped. The parcel is currently in transit with Aramex. You can follow the parcel with the Aramex tracking number in your account.
- d05: Dear customer, please accept our apologies for the trouble. About your order 4507: please send us a photo of the damaged item and its box. Reply to this message with the photo so we can review your case.
- d06 (**template**): Hello, your refund request needs approval from our finance team about your order 5017. The amount is 420.00 TND; it is 9 days late; refunds above 300.00 TND need this approval. Our finance team reviews the request and we reply to you with their decision. Refunds above 300 TND need approval from our finance team. The refund is not approved yet.
- d08: Dear customer, order 4514 is currently undergoing processing. Could you tell us if you would prefer to keep cash on delivery or pay by card?

**llama3.2:1b**
- d01: Dear customer, about your order 5042: your refund of 74.90 TND is approved. The money goes back to the card you paid with. The money goes back to your card.
- d03: Hello, order 4513. The next step is: You can follow the parcel with the Aramex tracking number in your account.
- d05: Dear customer, please accept our apologies for the trouble. Order 4507: Please send us a photo of the damaged item and its box. Reply to this message with the photo so we can review your case.
- d06 (**template**): (same template text as gemma3:1b d06)
- d08: Dear customer, we have received your order 4514 and are processing it. Could you tell us if you want to keep cash on delivery or pay by card?

### Choice rule (fixed in advance)
- Models ≤ 1.5 GB as loaded: qwen2.5:1.5b (1.2), gemma3:1b (0.9), llama3.2:1b (1.5, exactly at the limit).
  qwen3:1.7b (1.7 GB) is out by size.
- 80% of qwen2.5:3b's first-try rate (100%) = **80%**. qwen2.5:1.5b 100% ✓ · llama3.2:1b 78.6% ✗ · gemma3:1b 64.3% ✗.
- Best first-try among them: **qwen2.5:1.5b (100%)**. No tie.

### Safety and calls
- **0 API calls:** 79 `llm_call` lines in the 10 run traces, all `ollama`; **0 groq, 0 google**. The thinking test
  (2 local Ollama calls) was the only extra call.
- Free RAM before each model: 2.0–2.8 GB of 7.7 GB (lowest 2.0 GB, before qwen3:1.7b). Not critical, no swap
  problem seen. All models ran 100% on the GPU and were unloaded after (`ollama ps` empty at the end).
- Traces: `traces/run_20261028_185932_605700` / `_185956_336964` (qwen2.5:3b), `_190025_583725` / `_190047_264773`
  (qwen2.5:1.5b), `_190205_770383` / `_190227_962052` (qwen3:1.7b), `_190259_023219` / `_190336_778117` (gemma3:1b),
  `_190403_529466` / `_190427_736775` (llama3.2:1b); dev first, then v1. Raw console output: `out/t13e/*_dev.txt`,
  `*_test.txt`, memory snapshots `*_mem.txt` (git-ignored).
- Tests: no code changed; offline suite on this branch **318/318 passed** (42 s).
- Time: 18:48 → about 19:10 (~25 min of 1 h; the 4 pulls took ~10 min).

### 3 sentences
**Pick: qwen2.5:1.5b.** Under the fixed rule it is the only model ≤ 1.5 GB above 80% of the baseline (it matches
qwen2.5:3b at 14/14 first try with 0 invented numbers), at half the GPU memory and with the Apache 2.0 licence.
**Runner-up: qwen3:1.7b** (13/14, also Apache 2.0), but it loads at 1.7 GB, above the limit, and its one failure
spoke about "the client" in the third person. Among the models within the size limit the next is llama3.2:1b, at
78.6%, below the 80% bar, because it copies prompt labels into the reply. **Main risk:** only 14 practice decisions,
and the SLM prompt was written and tuned on qwen2.5:3b, which favours the same family. The real test is the held-out
v2 set at the final LoRA benchmark.

## 4. Problems
- **Small, practice-only sample** (14 decisions; v1 is spent and dev was used to write the prompt). A tie at 100%
  between 3b and 1.5b says "no visible loss here", not "equal quality".
- **Prompt bias:** the prompt was built with qwen2.5:3b (T05/T05b). It may suit the Qwen family better than
  gemma/llama. With their own prompt or a LoRA, the 1B models could do better.
- **No speed gain:** 1.5b is only a little faster (2.59 vs 2.75 s per reply). The gain is GPU memory (−0.95 GB) and
  the licence, not time.
- The `config.yaml` comment describes another PC ("RTX 3050 Ti Laptop, 4 GB"). This PC has an RTX 4050 Laptop, 6 GB.
  I changed nothing (not allowed). The comment can be updated when Yassine decides.
- The check called qwen3's "before any … refund is processed" a refund promise. It is a strict match on a conditional
  sentence; I did not change the check (not allowed).
- Free RAM was low on this PC (2.0–2.8 GB) but never critical.

## 5. Questions for the Brain
1. Do you accept **qwen2.5:1.5b** as the LoRA/QLoRA base, and should `config.yaml` switch the SLM to it now or only
   after the LoRA is trained? (Yassine decides; I changed nothing.)
2. qwen2.5:3b uses the **Qwen Research Licence** (non-commercial). For a university project that is fine, but should
   the report say the switch also fixes the licence?
3. Should the next task also count "prompt labels copied into the reply" ("length:", "The next step is:") as a check
   problem? The check catches it today only when the label has numbers in it.

## 6. Next step
Suggestion: when Dali's D3 data is ready, a LoRA/QLoRA task on qwen2.5:1.5b (Unsloth or PEFT), measured once on the
held-out v2 set against qwen2.5:3b without an adapter. Until then, optionally switch `config.yaml` to qwen2.5:1.5b
(one line) to free about 1 GB of GPU memory for the local agents.
