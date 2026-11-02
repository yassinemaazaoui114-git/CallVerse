# T33 report — Style policy demo check: OFF vs ON on 5 demo messages

**Top line:** with the style policy ON (the policy trained on the team's real ratings), **5/5 decisions are unchanged**,
with 0 wrong writes, 0 leaks, 0 crashes and 0 Groq tokens. The ON replies are longer and warmer: they add a greeting
and, with `warm_next_step`, a closing line ("We will message you here…").
- In 4 of 5 ON replies the small reply model (SLM) failed the style check twice, so the fixed **template** wrote the
  reply.
- Average reply time: OFF 17.5 s, ON 18.9 s (+1.4 s).

`config.yaml` stays OFF. Tests 1879/1879.

## 1. In plain words
We sent 5 demo messages twice: once as the demo runs today, and once with the "reply style" learner switched on.
The learner only chooses how the answer is worded, never what is decided. In all 5 cases the decision was the same.
With the learner on, the answers greet the client, say sorry first, and often end with what happens next. The team
rated replies like these higher in their ratings. But the small writing model rarely manages that wording by itself,
so most of these answers come from a fixed sentence pattern. They are correct but a little stiffer, and each one takes
about 1–3 seconds longer.

## 2. Done
- `scripts/style_demo_check.py` (new). It runs 5 messages through the same door as the apps (`run_t14c.run_one`,
  i.e. `web_chat.send`), each twice: policy OFF, then ON.
  - The switch is turned on only inside the script (the loaded config is patched in memory). `config.yaml` is
    unchanged.
  - Policy file: `out/rl5_policy.json` (REAL ratings, T31). The random draw uses a fixed seed (33).
  - Fresh ShopNova and Atlas data for every run, and a fresh tickets file for every run (see Problems).
  - It records the decision the reply writer got before and after the policy. "Decision unchanged" compares every
    key except `reply_style`, between the OFF and the ON run.
  - Outputs: `out/t33_style_demo.md` (side by side), `out/t33_style_demo.json`, `out/t33_style_demo.log`.
- The 5 messages:
  - demo flow F4 (ShopNova status) and demo flow F3 (Atlas compensation that waits for the admin);
  - 3 from the practice (dev) sets: decline t05, angry p06, Atlas decline a07.
  - The demo has no decline or angry message. The only Atlas "ask" message is in a locked set (`tests/data`), so F3
    takes its place.
- DBs: `shopnova.db`, `atlas.db` and `callverse.db` were backed up to `out/t33_dbbackup/` before the runs and put
  back after (`cmp` identical, both runs).

## 3. Evidence
- `python -m scripts.style_demo_check` (`CALLVERSE_AGENTS_SET=local`). Trace
  `traces/run_20261102_185546_398109.jsonl`.
- **Decisions unchanged 5/5.** The policy changed only `reply_style` in 5/5. Wrong writes 0, leaks 0, crashes 0, Groq
  tokens 0.
- **Time:** avg OFF 17.5 s, ON 18.9 s. Per message:

  | Message | Group | Style ON | OFF s | ON s | Reply source OFF / ON |
  |---|---|---|---|---|---|
  | F4 | shopnova/info/other | warm_next_step | 11.8 | 11.4 | slm / template |
  | t05 | shopnova/decline/other | warm_next_step | 18.5 | 20.6 | slm / template |
  | p06 | shopnova/ask/angry | warm_next_step | 25.5 | 25.4 | slm / slm |
  | a07 | atlas/decline/angry | warm | 12.2 | 14.9 | slm / template |
  | F3 | atlas/other/other | warm | 19.7 | 22.1 | slm / template |

- **Why the template:** in 4/5 ON runs, both SLM tries failed the style check (`styled_problems`, RL1b). The trace
  says "the first sentence must be one sentence about the client's feelings, before the sentences to copy" and
  "the first sentence must have no number". The SLM started with the facts, not a feelings sentence. After 2 tries the
  styled template writes the reply. It is correct by construction, and it costs the 2 failed tries (~1–3 s).
- a07 chose `warm`, although `warm_next_step` has the best mean in that group (1.0 vs 0.75, T30 section 7). This is
  Thompson sampling: it still draws, so a group with few ratings (n = 8) sometimes gets its second-best style.

### The 5 replies side by side

**F4 — ShopNova status (demo F4).** Client: "Hi, where is my order 4511?"
- OFF: Hello, your order 4511 is being prepared.
- ON (warm_next_step): Hello, I'm sorry for the trouble. Your order 4511 is being prepared. We will message you here if
  anything changes.

**t05 — ShopNova decline.** Client: "what happened to my order 4510? Refund if you can't deliver"
- OFF: I'm sorry for the trouble. Order 4510 is on its way and is not late: it is due by 2026-10-10. A refund for a
  late delivery is possible when an order is more than 5 days late.
- ON (warm_next_step): Hello, I'm sorry for the trouble. Order 4510 is on its way and is not late: it is due by
  2026-10-10. A refund for a late delivery is possible when an order is more than 5 days late. If you think something
  is wrong, reply here with the details and we will check it.

**p06 — Angry client.** Client: "I FUCKING HATE YOU THIS IS THE THIRD TIME IN A ROW YOU ARE LATE WITH ONE OF MY PACKAGES
Order 4512."
- OFF: I'm sorry for the trouble. Please confirm that you want a free replacement Wireless Earbuds for order 4512.
- ON (warm_next_step): Hello, I'm sorry to hear that waiting for your parcel that doesn't arrive is causing you
  stress. Please confirm that you want a free replacement Wireless Earbuds for order 4512.

**a07 — Atlas decline.** Client: "I cancelled booking 7002 and I want my money back."
- OFF: I'm sorry for the trouble. Hotel booking 7002 is non-refundable, so it is not refunded after cancelling.
- ON (warm): Hello, I'm sorry for the trouble. Hotel booking 7002 is non-refundable, so it is not refunded after
  cancelling.

**F3 — Atlas compensation (demo F3).** Client: "My flight 7004 was very delayed. I want compensation."
- OFF: I'm sorry for the trouble. Your compensation of 839.50 TND for booking 7004 needs approval from our finance
  team. We will reply here as soon as it has been reviewed.
- ON (warm): Hello, I'm sorry for the trouble. Your compensation of 839.50 TND for booking 7004 needs approval from our
  finance team. We will reply here as soon as it has been reviewed.

- Checks: no change in `callverse/`, `config.yaml` or `tests/data/`. Nothing under `models/` or `data/raw/`, and no
  secrets.

## 4. Problems
- **First run invalid, re-run.** In my first run the OFF and ON runs shared one tickets file. For F3 the ON run found
  the OFF run's pending approval, and the channel answered "already with our finance team" without calling the
  pipeline (4/5 unchanged). I fixed the script (a fresh tickets file per run) and ran it again. The numbers above are
  from the second run. These are demo and dev messages, not a locked set.
- **The SLM rarely writes the styled opening by itself** (1 of 5). ON replies are mostly the fixed template. They are
  safe and correct, but less varied, and each costs 2 wasted SLM tries.
- **The ratings rated the SLM's styled replies (RL1 sheet), but the demo mostly shows the template.** The team's
  preference for `warm_next_step` may not carry over fully to the template wording.
- **One run per message.** The SLM and the Thompson draw are random, so another run could pick another style (a07).
- **The angry case p06 uses a real tweet with a swear word.** For the live demo, another angry message may be better.

## 5. Questions for the Brain
1. **ON or OFF for the demo?** Evidence:
   - For ON: 5/5 decisions unchanged, 0 wrong writes, 0 leaks. The replies are warmer and end with the next step,
     which the team rated higher (warm_next_step best in 11/13 groups).
   - Against: +1.4 s average, and 4/5 replies come from the template after 2 failed SLM tries. The style is chosen at
     random within a group, so a live demo can surprise. F4's ON reply says "sorry for the trouble" to a plain
     status question.
2. If ON: should the policy be made deterministic for the demo (always the best style per group, no draw)? That would
   be a code change in `callverse/`, not part of T33.

## 6. Next step
Yassine decides ON or OFF from section 3. If ON, a small task flips `learning.style_policy` in `config.yaml` (and
perhaps uses the best style without a draw) and re-runs the 72-message regression.

Merge line for Yassine (after the Brain's review): `git checkout main && git merge --no-ff origin/feat/t33-style-demo`
