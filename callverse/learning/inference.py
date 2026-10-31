"""Inference entry point of the style RL: pick a style, write the reply, judge it, (optionally) learn.

    from callverse.learning.inference import respond, select_style
    out = respond(decision, situation, history=None)   # -> {"style", "reply", "used_template", "evaluation"}

select_style(situation): the saved policy checkpoint (models/agent_f/style_policy.json) if there is one, else
DEFAULT_STYLE, the best fixed style of the simulated benchmark. The policy only picks the wording style: the
Coordinator decision (facts, amounts, rules, next step) goes to the writer untouched.
learn(record, style, evaluation, policy): one bandit update from Agent F's reward (None = UNKNOWN = skipped).
"""
from __future__ import annotations

import json
from pathlib import Path

from callverse.learning.style_policy import GaussianThompson, LinUCB, StylePolicy
from callverse.learning.style_writer import STYLES, write_with_slm
from callverse.quality.reward import evaluate_response
from callverse.quality.satisfaction import MODEL_DIR

DEFAULT_STYLE = "apology_next_step"          # best fixed style on the simulated evaluation (docs/agent_f.md)
POLICY_PATH = MODEL_DIR / "style_policy.json"
LOADERS = {"linucb": LinUCB.load, "thompson_beta": StylePolicy.load}


def load_policy(path: Path | None = None):
    """The saved policy, or None. The file's "kind" says which class wrote it (default: Beta Thompson)."""
    path = Path(path or POLICY_PATH)
    if not path.exists():
        return None
    kind = json.loads(path.read_text()).get("kind", "thompson_beta")
    return LOADERS.get(kind, StylePolicy.load)(path)


def select_style(situation: dict, policy=None, explore: bool = False) -> str:
    if policy is None:
        return DEFAULT_STYLE
    return policy.choose(situation) if explore else policy.best(situation)


def respond(decision: dict, situation: dict, history: list[dict] | None = None, policy=None, chat_fn=None,
            explore: bool = False, stacker=None) -> dict:
    """Full step: style -> real writer (SLM, template fallback) -> Agent F dual reward."""
    style = select_style(situation, policy, explore)
    written = write_with_slm(decision, style, history, chat_fn)
    user_turns = [{"role": "user", "text": m.get("content") or m.get("text") or ""} for m in (history or []) if m.get("role") == "user"]
    record = {"ticket_id": situation.get("ticket_id"), "company": situation.get("company") or decision.get("company"),
              "messages": user_turns + [{"role": "assistant", "text": written["reply"]}],
              "situation": situation, "style": style, "decision": decision}
    evaluation = evaluate_response(record, stacker=stacker)
    return {"style": style, "reply": written["reply"], "used_template": written["used_template"],
            "evaluation": evaluation, "record": record}


def learn(out: dict, policy, reward_key: str = "reward") -> None:
    """Bandit update from one respond() result. UNKNOWN correctness (reward None) is never learned from."""
    r = out["evaluation"][reward_key] if reward_key == "reward" else (
        None if out["evaluation"]["correctness"] == "UNKNOWN" else
        (out["evaluation"]["satisfaction"] if out["evaluation"]["correctness"] == "PASS" else 1.0))
    policy.update(out["record"]["situation"], out["style"], r)
