# Final architecture: Agents E and F (research components)

Both agents follow the prototype's locked rule (CLAUDE.md): **agents never act directly**. Agent E returns a *proposal*. Agent F returns *reports and scores*. Rules (the Coordinator, or Worker D's validator in the offline tests) decide what happens.

Neither component is wired into `callverse/`. That needs an approved task.

## How E and F fit around the prototype

```
 client message ─► Intake (prototype) ─► ticket {main_reason, priority_label, priority_score}
                                               │
                        ┌──────────────────────┴───────────────────────┐
                        ▼                                              ▼
       prototype flow: queue → Agent A/B → Coordinator → SLM     v4/d/bridge.TicketBook
                        │                                     (reason → 4 Agent E categories)
                        ▼                                              │ aggregate snapshot (no text)
              closed conversation trace                                ▼
              (traces/*.jsonl, pipeline_done)                  Agent E adapter (v4/e/adapter.py)
                        │                                     RL proposal + mask + urgent shield
                        ▼                                              │ proposal
              Agent F (v4/f/agent_f.py)                                ▼
              score + validity, quality flags,               independent rule check (v4/d/bridge.validate)
              rule/knowledge warnings, owner report           → execute or refuse (Coordinator's job)
                        │
                        └─► F→E contract (v4/d/fe_contract.py): reward channel only if F's flag
                            AND a passing validation card agree; otherwise KPI only (today: always KPI only)
```

## Agent E (capacity proposals)

**Input** (snapshot, no message text). Per category, in the order A_status, B_refund, C_urgent, D_availability:
- sessions;
- waiting tickets (priority label, score, minutes waited);
- arrivals in the last step and their EWMA.

Plus time step, fallback state, budget spent and capacity.

**Pipeline in the adapter**
1. Build the observation and action mask with the simulator's **own** code (`EnvV3._obs`, `EnvV3.action_mask` on a read-only snapshot view; tested as equal on real states).
2. Optional **urgent shield**: a queue-C floor (static or Erlang-based) removes actions that would take sessions from queue C below the floor.
3. The tiny RL network (DQN family, 8.1k params, about 1 ms on CPU) picks the best **allowed** action.
4. If the checkpoint is missing or broken, the classical backup (Fluid MPC) proposes instead, and `fallback_reason` says why.
5. Output: action, policy name, Q-values, mask, shielded mask, veto flag and reason, audit (model SHA256, latency).

**Guarantees and their limits**

| Guaranteed by rules (tested) | NOT guaranteed |
|---|---|
| Every proposal is valid under the simulator mask (budget, capacity, minimum active sessions) | Future SLAs: a mask constrains **allocation**; whether tickets are served on time depends on demand the agent cannot see |
| Queue C ≥ 2 (≥ the floor with the shield) | |
| Fallback never serves HIGH tickets and is capped at 25% of the day | |
| Worker D's independent validator agrees with the mask on all 13 scenario families | |

**Final E policy:** see `AGENT_E_NEW_EVALUATION.md` and `MODEL_SELECTION_AND_LIMITATIONS.md` (filled in after Worker E's pre-registered TEST4).

## Agent F (M7 Quality & Knowledge)

| Responsibility | Component | Model? |
|---|---|---|
| 1. Satisfaction for every closed conversation | `m7/satisfaction_v4`: TF-IDF + Ridge (193k params, about 3 ms), with **validity metadata**. French and other unvalidated languages get no score. English ShopNova is marked "indicative, out of domain" | the only learned part |
| 2. Quality review | `m7/quality_v4`: 14 deterministic checks (false vs unsupported claim, missed entitlement, leaks, language mismatch, send-backs, escalations…). Every flag has trace refs, re-verified against the trace | rules |
| 3. Outdated / inconsistent rules and knowledge | `m7/rule_audit_v4`: consistency (text vs condition, code references), coverage gaps, governance (unreviewed AI wording), usage evidence. **Freshness = NOT CHECKABLE**: there are no dated sources | rules |
| 4. Owner report | `owner_report()` → JSON + Markdown with evidence | rules |
| 5. Feedback to E | `feedback_v4` + `v4/d/fe_contract.py`. The gate (from V3, fixed before evaluation) requires genuine customer ratings of support conversations | gate closed |

**Learning from real reviews**
- `learn_from_reviews()` fits an isotonic calibration on genuine ratings once they exist.
- Reviews contract: `v4/f/contracts/reviews_contract.md`.
- Annotation protocol: `v4/f/ANNOTATION_PROTOCOL.md`.

## Why these choices

**Why rules where rules suffice.** Each check has an exact definition in the prototype (Coordinator checks, policy conditions, SLM leak pattern). A model would add cost and error without making those definitions more exact.

**Why a tiny RL policy at all.** Agent E's research question is whether learning beats hand-made staffing rules in a validated simulator. The answer is evidence either way. The classical rules are kept as baselines and as a safe backup, so the RL component can be shown without putting urgent customers at risk.
