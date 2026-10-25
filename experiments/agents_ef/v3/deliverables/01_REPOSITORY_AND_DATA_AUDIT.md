# 01 — Repository and data audit

## 1. Repository state

- **Branch:** `research/agents-e-f-tiny-models`.
  - All V3 work is local commits on this branch.
  - Nothing was pushed, merged or opened as a PR: the V3 rule requires separate approval for that.
- **Untouched:** `main`, teammate branches and the prototype code under `callverse/`.
- **Research code:** `experiments/agents_ef/`.
  - `env/`, `rl/`, `baselines/`, `bench/`, `integration/`: v1/v2 code, reused.
  - `v3/`: this benchmark.
- **V3 edits to existing files** (both minimal):
  1. `rl/agents.py`: a `dueling_dqn` option in `make_agent`.
  2. Root `.gitignore`: ignores `v3/**/*.pt`.
- **Not in git:** checkpoints, raw datasets, model caches and the venv. They stay in the session scratchpad.
  - Hashes: `RECOVERY_MANIFEST.json` (v1/v2) and the V3 checkpoint manifest (`CHECKPOINT_MANIFEST_E.json`, written at freeze).

## 2. Evidence that existed before V3 (Phase 0)

The recovery manifest is `RECOVERY_MANIFEST.json`. It lists SHA256 hashes for:
- 57 Agent E runs:
  - v1 env: 15 Dueling DDQN, 6 DQN, 6 PPO, 3 Double DQN, 3 Tabular Q;
  - v2 intake env: 15 Dueling DDQN, 3 each Double DQN, DQN, PPO.
- 31 Agent F checkpoints.

Reports kept as history: `reports/AGENT_E_SCIENTIFIC_JUSTIFICATION.md`, `reports/REPORT_agents_e_f.md`, `reports/REPORT_v2_agents_e_f.md`.

- **Validity finding:** v1/v2 share one random generator. The arrivals depend on the policy, so the "paired" CIs of v1/v2 are not valid as paired intervals. See `02_SIMULATOR_VALIDATION.md` §1.
- v1/v2 results are **superseded** by v3. Nothing was deleted.

## 3. Execution environment

| Item | State |
|---|---|
| Compute | Linux sandbox, 4 shared CPU cores, no GPU |
| User's Windows PC with RTX 4050 | **BLOCKED**: no remote connection from this session. GPU / VRAM numbers are NOT VERIFIED. |
| QCRI GPU processes | not observable from here (no PC access); nothing was stopped or competed with |
| Disk | about 6.4 GB free at the start of Gate C; checkpoints are small (Agent E < 100 KB each) |

## 4. Data used by Agent E

**No CallVerse contact logs were reachable**, so the Agent E world is simulated. Sources:

| Source | Used for | Kind |
|---|---|---|
| Prototype code: `callverse/intake/priority.py`, `config.yaml`, `callverse/queues/queue.py` | Intake priority formula, R-ESC-01 threshold, queue discipline | code (authoritative) |
| Olist Brazilian e-commerce (public, Kaggle mirror) | late-delivery share 8.1%, days-late distribution, high-value share 10.4%, flat daytime demand shape, day-to-day CV 0.43 | **real public data** (orders, not support contacts) |
| Queue mix, service times, patience, emotion, SLA tiers, fallback parameters, peak shapes | simulator parameters | **INVENTED**, listed in `02_SIMULATOR_VALIDATION.md` §5 |

## 5. Data used by Agent F

Details: `v3/f/DATASETS.md`, `v3/f/data_provenance.json`.

| Dataset | Label type | Verdict |
|---|---|---|
| USS (SGD, MWOZ, ReDial, CCPE EN; JDDC ZH): 6,772 dialogues after de-duplication | human annotator satisfaction 1–5 (3–7 annotators; α 0.20–0.28 for EN, 0.52 for JDDC) | **primary benchmark** |
| Amazon Multilingual Reviews EN/FR (v2 subset) | self-reported **product** stars | auxiliary, reported separately |
| DialEval-2 / DCH-2 helpdesk | customer-satisfaction annotations | **BLOCKED**: needs a user agreement, not accepted on the user's behalf |
| Saif7800/customer_qa_dataset | `csat` | **REJECTED**: LLM-generated, CSAT is almost a function of the sentiment tag |
| Flipkart CSAT (sharmila122125) | survey CSAT | candidate only: no dialogue text, licence unverified |
| rootfs/user-satisfaction-dataset | 4 intent-like classes | rejected: not a rating |
| Kaggle support tickets, LEGO corpus | CSAT / interaction quality | NOT ACCESSED (login needed) |
| Local CallVerse datasets on the user's PC | — | **BLOCKED** (no access) |

**No genuine customer ratings of support interactions were reachable.** The label types are never pooled.

## 6. Privacy and safety checks

- No raw customer text, datasets, secrets or `.env` files are committed. Results files contain only aggregates or IDs.
- No gated dataset agreement was accepted.
- No external upload of data.
- No global tools, MCP servers or system settings changed.
