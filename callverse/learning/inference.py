"""Inference entry point of the style RL: pick a style, write the reply, judge it, (optionally) learn.

    from callverse.learning.inference import respond, select_style
    out = respond(decision, situation, history=None)   # -> {"style", "reply", "used_template", "evaluation"}

select_style(situation): a saved policy checkpoint (models/agent_f/style_policy.json, written by policy_eval.py) if
given, else the mood rule learned on the simulated TRAIN personas (DEFAULT_RULE), else DEFAULT_STYLE. The policy only picks the wording style: the
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

DEFAULT_STYLE = "apology_next_step"          # best single fixed style (fallback when no situation is known)
# Rule learned on the TRAIN simulated personas and selected on VAL (policy_eval.py); on the 40-persona check sets it
# scores 3.62 / 3.56 vs 3.50 / 3.55 for the fixed style (docs/agent_f.md). Simulated evidence only.
DEFAULT_RULE = {"upset": "apology_next_step", "calm": "short"}
UPSET = {"anger", "disgust", "sadness", "fear"}
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
    """Saved policy if given; else the train-learned mood rule; DEFAULT_STYLE when the emotion is unknown."""
    if policy is not None:
        return policy.choose(situation) if explore else policy.best(situation)
    if not situation.get("emotion"):
        return DEFAULT_STYLE
    return DEFAULT_RULE["upset" if situation["emotion"] in UPSET else "calm"]


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
