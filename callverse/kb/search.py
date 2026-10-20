"""Policy search (RAG): find the ShopNova rules that match a question BY MEANING.

Why by meaning? A client (or an agent) rarely uses the rule's own words: "my parcel is a week overdue,
I want my cash back" shares almost no words with "Full refund for a delay of more than 5 days", but the
two texts mean nearly the same thing. The embedding model (M3, the same one Intake uses) turns each text
into a vector; texts with a similar meaning get vectors pointing the same way (high cosine similarity).

    search_policy(query, k=3) -> [{id, title, text, score}, ...]   best first

How it works:
  1. each rule is embedded once as "title. text" (vectors cached in policy_vectors.npz, git-ignored;
     rebuilt automatically when the policy file or the model changes);
  2. the query is embedded the same way;
  3. score = cosine similarity (= dot product, the vectors have length 1); the k best rules are returned.

Why a small numpy index and not a vector database? 8 rules fit in a tiny matrix: one multiplication
gives every score. Chroma/FAISS would add a library for no gain (they can replace it later).
The tool version (search_policy_tool) is what agents A and B call through the registry.
"""

import hashlib
from functools import lru_cache
from pathlib import Path

import numpy as np

from callverse import trace
from callverse.config import load_config
from callverse.intake.reasons import embed   # reuse Intake's M3 loader: one model in memory, not two
from callverse.kb.policies import POLICIES_PATH, load_policies

CACHE_PATH = Path(__file__).resolve().parent / "policy_vectors.npz"


def policy_text(rule: dict) -> str:
    """The text that is embedded for one rule: its title, then its text."""
    return f"{rule['title']}. {rule['text']}"


@lru_cache(maxsize=1)
def policy_vectors() -> np.ndarray:
    """One vector per rule (same order as load_policies()), read from the cache when it is still valid."""
    model_name = load_config()["intake"]["embedding_model"]
    # Fingerprint of the policy file + model name: if either changes, the cache is outdated.
    fingerprint = hashlib.sha256(POLICIES_PATH.read_bytes() + model_name.encode()).hexdigest()

    if CACHE_PATH.exists():
        cache = np.load(CACHE_PATH)
        if str(cache["fingerprint"]) == fingerprint:
            return cache["vectors"]

    vectors = embed([policy_text(r) for r in load_policies()])
    np.savez(CACHE_PATH, fingerprint=np.array(fingerprint), vectors=vectors)
    return vectors


def rank(query_vector: np.ndarray, vectors: np.ndarray, rules: list[dict], k: int) -> list[dict]:
    """The k rules whose vectors are closest to the query vector, best first (pure maths, no model)."""
    scores = vectors @ query_vector                    # cosine similarity with every rule
    best = np.argsort(-scores)[:k]                     # indexes of the k highest scores
    return [{"id": rules[i]["id"], "title": rules[i]["title"], "text": rules[i]["text"],
             "score": round(float(scores[i]), 3)} for i in best]


def search_policy(query: str, k: int = 3) -> list[dict]:
    """The k ShopNova rules that best match `query` by meaning. Traced as step "policy_search"."""
    rules = load_policies()
    k = max(1, min(int(k), len(rules)))                # at least 1, at most every rule
    results = rank(embed([query])[0], policy_vectors(), rules, k)
    trace.log("policy_search", "kb", {"query": query, "k": k,
                                      "results": [{"id": r["id"], "score": r["score"]} for r in results]})
    return results


# Tool answers are re-sent at every later model call of the agent's turn, so they are kept short (T07):
# the 2 best rules, each text cut to about 300 characters. The full text stays in the policy file.
TOOL_K = 2
TOOL_TEXT_CHARS = 300


def search_policy_tool(query: str, k: int = TOOL_K) -> dict:
    """Tool version for the agents: a dict like every other tool (the rules are under "results")."""
    if not isinstance(query, str) or not query.strip():
        return {"error": "give a non-empty query"}
    results = [{**r, "text": r["text"][:TOOL_TEXT_CHARS]} for r in search_policy(query, k)]
    return {"results": results}


SCHEMA = {
    "type": "function",
    "function": {
        "name": "search_policy",
        "description": "Find the ShopNova rules that match a request, by meaning.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},   # k is not offered: agents always get the 2 best
            "required": ["query"],
        },
    },
}
