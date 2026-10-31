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

T21: one index per company, with its own cache file. An agent only ever searches its ticket's company.
"""

import hashlib
from functools import lru_cache

import numpy as np

from callverse import companies, trace
from callverse.config import load_config
from callverse.intake.reasons import embed   # reuse Intake's M3 loader: one model in memory, not two
from callverse.kb.policies import load_policies


# BGE models search best when the QUERY (not the rule text) starts with this instruction (T23: top-2 30/30 on val).
QUERY_PROMPT = "Represent this sentence for searching relevant passages: "


def embed_query(query: str) -> np.ndarray:
    """The vector of a search question: the BGE instruction + the question. Rules are embedded without it."""
    return embed([QUERY_PROMPT + query])[0]


def policy_text(rule: dict) -> str:
    """The text that is embedded for one rule: its title, then its text."""
    return f"{rule['title']}. {rule['text']}"


@lru_cache(maxsize=4)
def policy_vectors(company: str = companies.DEFAULT) -> np.ndarray:
    """One vector per rule of this company (same order as its rules file), read from its cache when still valid."""
    model_name = load_config()["intake"]["embedding_model"]
    rules_path, cache_path = companies.path(company, "rules_file"), companies.path(company, "policy_cache")
    # Fingerprint of the policy file + model name: if either changes, the cache is outdated.
    fingerprint = hashlib.sha256(rules_path.read_bytes() + model_name.encode()).hexdigest()

    if cache_path.exists():
        cache = np.load(cache_path)
        if str(cache["fingerprint"]) == fingerprint:
            return cache["vectors"]

    vectors = embed([policy_text(r) for r in load_policies(rules_path)])
    np.savez(cache_path, fingerprint=np.array(fingerprint), vectors=vectors)
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
    results = rank(embed_query(query), policy_vectors(), rules, k)
    trace.log("policy_search", "kb", {"query": query, "k": k,
                                      "results": [{"id": r["id"], "score": r["score"]} for r in results]})
    return results


# Tool answers are re-sent at every later model call of the agent's turn, so they are kept short (T07):
# the 2 best rules, each text cut to about 300 characters. The full text stays in the policy file.
TOOL_K = 2
TOOL_TEXT_CHARS = 300


def company_search_tool(company: str, query: str, k: int = TOOL_K) -> dict:
    """The tool for another company than ShopNova: the same search, in that company's own rules and index.
    `company` is set by our code (atlas_tools.py): the model never chooses it."""
    if not isinstance(query, str) or not query.strip():
        return {"error": "give a non-empty query"}
    rules = load_policies(companies.path(company, "rules_file"))
    k = max(1, min(int(k), len(rules)))
    results = rank(embed_query(query), policy_vectors(company), rules, k)
    trace.log("policy_search", "kb", {"company": company, "query": query, "k": k,
                                      "results": [{"id": r["id"], "score": r["score"]} for r in results]})
    return {"results": [{**r, "text": r["text"][:TOOL_TEXT_CHARS]} for r in results]}


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
