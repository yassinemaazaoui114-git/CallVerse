# T13b report — Merge into main + context-length benchmark (qwen3.5:4b)

## 1. In plain words
Our T11–T13 work is now merged into `main` on this PC (no conflicts, all 307 tests pass), but **`main` is not
pushed yet**: the push was blocked by Claude Code's permission check, so Yassine must push it himself.
Then we measured how much "memory for text" (context) the local test model can have on the 6 GB GPU. Up to
16,384 tokens it runs fully on the GPU; at 32,768 part of it moves to the CPU, so the rule picks **16,384**.
But the biggest prompt our agents ever send is only about **2,300 tokens**, so even 4,096 is enough and nothing
was ever cut. Keeping the agent model and the reply model in memory together (setup B) is **not possible** on
this GPU: Ollama always unloads one to make room, even at the smallest context.

## 2. Done
- Step 0: Ollama answered (`ollama list`, `cv-qwen3.5-4b` listed); `git fetch` worked (Yassine ran it, I ran it
  again at 10:17: `origin/main` = `d125959`, `origin/feature/t13-test-model` = `a201a22`, t12 contained in t13).
- Merge: `git checkout main`, `git pull --ff-only` (already up to date), `git merge --no-ff
  origin/feature/t13-test-model` → **`b814bfe`**, 0 conflicts. Tests on the merged `main`: **307/307**.
- **`git push origin main` was refused by the Claude Code permission check** (not by GitHub). Not retried.
- Branch `feature/t13b-context` from the new local `main`; first commit `5f2998b` = this task file + `tasks/NEXT.md`.
- 5 Ollama copies `cv-qwen3.5-4b-ctx<N>` (Modelfile `FROM qwen3.5:4b` + `PARAMETER num_ctx N`, exactly as T13;
  `ollama show --parameters` = same values as `cv-qwen3.5-4b` except `num_ctx`). The ctx8192 copy got the
  same id as `cv-qwen3.5-4b` (`a2a264674625`) = identical.
- Temporary message file `out/t13b_refund_messages.json` (d05, d20, d24 copied unchanged; git-ignored).
- **How the copy was forced (deviation, see Problems 2):** before each run, `ollama cp cv-qwen3.5-4b-ctx<N>
  cv-qwen3.5-4b`, then `CALLVERSE_AGENTS_SET=local CALLVERSE_FORCE_AGENTS_MODEL=cv-qwen3.5-4b python -m
  scripts.run_live_check --file out/t13b_refund_messages.json`. `ollama ps` showed the right CONTEXT in every run.
- Setups (I stopped the Ollama tray app and ran `ollama serve` myself, so the settings are exact and known):
  - **Setup A:** `OLLAMA_MAX_LOADED_MODELS=1` (one model at a time = "agent alone, swaps with the SLM"), rest default
    (`OLLAMA_KEEP_ALIVE` 5m, `OLLAMA_CONTEXT_LENGTH` 0). Log: `out/t13b/server_A.log`.
  - **Setup B:** `OLLAMA_MAX_LOADED_MODELS=2`, `OLLAMA_KEEP_ALIVE=30m`, rest default. Log: `out/t13b/server_B.log`.
- Sampler during each run: `ollama ps` + `nvidia-smi` memory every ~1 s (`out/t13b/samples_<setup>_<ctx>.txt`).
- Clean-up: `cv-qwen3.5-4b` put back from a backup copy (id `a2a264674625`, `num_ctx 8192` = as before the
  task); deleted the backup and the ctx 4096 / 6144 / 8192 / 32768 copies; **kept `cv-qwen3.5-4b-ctx16384`**
  (the recommended one). No code, `config.yaml`, prompt or test change. `.env` not read. `tests/data/*` not run.

## 3. Evidence
**Ollama 0.40.12** (auto-updated from 0.40.11 on 2026-10-28 09:55; T13 ran on 0.40.11). GPU: RTX 4050 Laptop,
6,141 MiB (about 0.4 GB used by Windows with no model loaded). Same 3 messages, once per value.

**Setup A: agent model alone (`OLLAMA_MAX_LOADED_MODELS=1`)**

| Context | % GPU / % CPU (agent, SLM) | GPU memory peak | s per agent call (avg / max) | s per message (avg / max) | Largest prompt tokens | "truncating" warning? | d05 / d20 / d24 |
|---|---|---|---|---|---|---|---|
| 4,096 | agent 3.1 GB 100% GPU · SLM 2.2 GB 100% GPU | 4,152 MiB | 4.9 / 11.3 | 36.7 / 48.8 | 2,261 of 4,096 | no | PASS / PASS / PASS |
| 6,144 | agent 3.3 GB 100% GPU · SLM 100% GPU | 4,304 MiB | 4.9 / 12.2 | 36.9 / 48.6 | 2,246 of 6,144 | no | PASS / PASS / PASS |
| 8,192 | agent 3.4 GB 100% GPU · SLM 100% GPU | 3,963 MiB | 4.9 / 12.7 | 37.5 / 50.3 | 2,246 of 8,192 | no | PASS / PASS / PASS |
| 16,384 | agent 3.6 GB 100% GPU · SLM 100% GPU | 4,139 MiB | 4.6 / 11.6 | 34.9 / 46.9 | 2,261 of 16,384 | no | PASS / PASS / PASS |
| 32,768 | **agent 4.8 GB 23% CPU / 77% GPU** · SLM 100% GPU | 4,313 MiB | 5.6 / 14.1 | 41.4 / 56.0 | 2,222 of 32,768 | no | PASS / PASS / PASS → **stop** |

**Setup B: agent + SLM meant to be loaded together (`OLLAMA_MAX_LOADED_MODELS=2`, `OLLAMA_KEEP_ALIVE=30m`)**

| Context | % GPU / % CPU (agent, SLM) | GPU memory peak | s per agent call (avg / max) | s per message (avg / max) | Largest prompt tokens | "truncating" warning? | d05 / d20 / d24 |
|---|---|---|---|---|---|---|---|
| 4,096 | agent 3.1 GB 100% GPU · SLM 2.2 GB 100% GPU, **never both loaded** (0 of 154 samples) | 3,743 MiB | 4.5 / 10.9 | 34.2 / 45.9 | 2,261 of 4,096 | no | PASS / PASS / PASS |
| 6,144 | agent 3.3 GB 100% GPU · SLM 100% GPU, **never both loaded** (0 of 108 samples) | 3,895 MiB | 4.5 / 10.8 | 33.9 / 45.4 | 2,246 of 6,144 | no | PASS / PASS / PASS |
| 8,192 – 32,768 | not run (see below) | | | | | | |

- **Why setup B never loads both:** `server_B.log` has **12** lines `"llama-server model predicted to exceed
  available memory, evicting"`, e.g. agent at ctx 4,096 `predicted="2.8 GiB" ... available="2.9 GiB"` (the SLM
  loaded), and SLM `predicted="1.9 GiB"` with `available="1.9 GiB"` / `"2.0 GiB"` (the agent loaded). So even at the
  smallest context, Ollama unloads one model to load the other: setup B behaves like setup A. I stopped setup B
  after 6,144 because a bigger context only makes the agent model bigger (3.1 → 4.8 GB), so it cannot fit better.
  `server_A.log`: 0 evictions (one model at a time, by setting).
- **Prompt cut:** 0 truncation warnings in all 7 runs. (The only "truncat" lines are llama.cpp's normal
  end-of-request status `truncated = 0`, 23 per run.) Stronger proof: the **largest agent prompt is 2,222–2,261
  tokens at every context**, the same 18 prompt sizes at 4,096 as at 32,768, so nothing was cut. On the full
  24-message practice set (T13 traces `run_20261024_222932_715828`, `run_20261024_224238_046191`) the largest agent
  prompt was **2,021**.
- **Same answers at every value:** d05 `info`, d20 `approve` + refund 4512 59.9, d24 `info`; 3/3 PASS in all
  7 runs; crashes 0, leaks 0, wrong writes 0.
- **API calls:** 0. The 7 traces of this task have 161 `llm_call` lines, all `ollama` (cv-qwen3.5-4b 133,
  qwen2.5:3b 28); 0 groq, 0 google. Traces: `traces/run_20261028_102844_117368`, `_103248_497319`,
  `_103541_619048`, `_103816_709419`, `_104053_133522` (A 4k→32k), `_104415_186027`, `_104744_243061` (B 4k, 6k).
- Raw files (git-ignored): `out/t13b/` (run output, samples, server-log slices, results per run).
- Time: 10:17 → about 10:55 (~40 min of 1.5 h).

**Recommended value, setup A:** **16,384**, the last value that ran 100% on GPU with no prompt cut (32,768 moved
23% of the agent model to the CPU and was the slowest: 41.4 s per message).
**Recommended value, setup B:** **none.** The two models never fit in memory together on this 6 GB GPU at any
tested context (4,096 and 6,144 already evict), so setup B cannot happen.

## 4. Problems
1. **`main` is merged locally but NOT pushed** (`main` = `b814bfe`, `origin/main` still `d125959`). The Claude
   Code permission check refused `git push origin main`. Yassine needs to push it himself
   (`! git push origin main`). `feature/t13b-context` is also not pushed yet (see Next step).
2. **The task's step 4 could not be followed as written.** `CALLVERSE_FORCE_AGENTS_MODEL=cv-qwen3.5-4b-ctx16384`
   fails because `llm.models_for()` only accepts a model listed in `config.yaml` (`models.agents_local`), and
   the task forbids changing `config.yaml`. Workaround (no repo change): copy each test copy onto the name
   `cv-qwen3.5-4b` before the run, then restore it at the end (done and checked: id `a2a264674625`, `num_ctx 8192`).
   Side effect: **all traces say `cv-qwen3.5-4b`** whatever the context. Which run used which context is in
   `out/t13b/samples_*.txt` (`ollama ps` CONTEXT column).
3. **The Ollama tray app is not running now.** I stopped it for the measurements. Restarting it from the script
   (twice) did not bring the server back. Yassine: start Ollama from the Start menu.
4. The rule's pick (16,384) gives no measurable gain over 4,096–8,192: same prompts, speed within noise
   (34.9–37.5 s per message). It only adds headroom (7× the largest prompt) for ~0.2 GB more GPU memory.
5. **d20 differs from T13:** here qwen3.5:4b called `propose_refund` on d20 in all 7 runs (Coordinator
   `approve`, refund 4512 59.9, allowed by the rules). In T13 (Ollama 0.40.11, 24-message run) it never proposed.
   Possible causes: the Ollama update, or the different order of messages. I did not investigate (not in scope).
6. Small notes: the GPU peak is sampled about once a second, so a short peak can be missed. Each run prints the
   usual Hugging Face warning (`unauthenticated requests to the HF Hub`, from the Intake's local models loading).
   This is not an LLM API call. `server_B.log` showed only **~1 GB of free system RAM** at one point, so a CPU
   spill would be slow. `tasks/NEXT.md`'s "Approved by" line still says "Ollama stays 0.40.11"; the task file
   (10:11) says 0.40.12 accepted. I followed the task file.

## 5. Questions for the Brain
1. Context for `cv-qwen3.5-4b`: switch to the rule's **16,384**, or keep **8,192** (already 3.6× the largest prompt,
   0.2 GB less)? It is Yassine's call, and the `config.yaml` comment "one agent turn is ~6,000 tokens" may need fixing:
   that is the sum over a turn, while one prompt is at most about 2,300.
2. Setup B (both models together): worth a later task? It would need about 0.1–0.5 GB less, e.g. the smaller SLM
   fallback `qwen2.5:1.5b` or Ollama KV-cache settings. Not tested here.
3. Should `CALLVERSE_FORCE_AGENTS_MODEL` accept any Ollama model name in the local set (a small code change), so a
   benchmark like this one does not need the copy-onto-the-name workaround?
4. d20 now proposes a refund with qwen3.5:4b (it never did in T13): re-check T13's "never proposes" conclusion on 0.40.12?

## 6. Next step
Yassine: push `main` (`git push origin main`) and start the Ollama app again. Then Brain review of this report and the
decision on the context value (a one-line `config.yaml` comment + Modelfile change in a later task).
