"""Shared LLM layer (M1 simulator, M2 agents).

Every LLM call of the project goes through chat(). The code never names a model or provider:
it asks for a ROLE ("agents", "simulator") and config.yaml says which models play that role,
in order. Switching model or provider = editing config.yaml only.

All providers are reached with the same `openai` SDK, because they expose an OpenAI-compatible API;
only the base_url and the API key change.
"""

import os
import time

from dotenv import load_dotenv
from openai import APIConnectionError, InternalServerError, NotFoundError, OpenAI, RateLimitError

from callverse import trace
from callverse.config import PROJECT_ROOT, load_config

# Read API keys from .env into environment variables (keys are never written in the code).
load_dotenv(PROJECT_ROOT / ".env")


class AllModelsFailed(RuntimeError):
    """Raised when every model of a role was skipped or failed."""


def chat(role_key: str, messages: list[dict], tools: list[dict] | None = None):
    """Send `messages` to the first available model of `role_key` and return the reply message.

    - Models are tried in the order of config.yaml (backup chain).
    - We move on to the next model when the problem is on the provider's side:
      rate limit (429), model not found (404), server error (5xx) or connection error.
    - We do NOT move on for other errors such as 400 (bad request): that means our request is
      wrong, so another model would fail too and the error must be fixed in our code.
    - A model whose API key is missing in .env is skipped (logged).
    - Provider, model, token usage and time are written to the trace.
    The returned object has `.content` (text) and `.tool_calls` (None or a list).
    """
    cfg = load_config()
    errors = []

    for entry in cfg["models"][role_key]:
        provider_name, model = entry["provider"], entry["model"]
        provider = cfg["providers"][provider_name]

        api_key = os.getenv(provider["key_env"])
        if not api_key:
            reason = f"missing {provider['key_env']} in .env"
            trace.log("llm_skip", "llm", {"role": role_key, "provider": provider_name,
                                          "model": model, "reason": reason})
            errors.append(f"{provider_name}/{model}: {reason}")
            continue

        # max_retries=0: we do our own fallback to the next model instead of waiting and retrying.
        client = OpenAI(base_url=provider["base_url"], api_key=api_key, max_retries=0, timeout=60)
        request = {"model": model, "messages": messages}
        if tools:
            request["tools"] = tools

        start = time.perf_counter()
        try:
            response = client.chat.completions.create(**request)
        except (RateLimitError, NotFoundError, InternalServerError, APIConnectionError) as e:
            # 429 / 404 / 5xx / network problem: log it and try the next model of the chain.
            trace.log("llm_fallback", "llm", {"role": role_key, "provider": provider_name,
                                              "model": model, "error": f"{type(e).__name__}: {e}"})
            errors.append(f"{provider_name}/{model}: {type(e).__name__}")
            continue
        seconds = round(time.perf_counter() - start, 3)

        message = response.choices[0].message
        usage = response.usage
        trace.log("llm_call", "llm", {
            "role": role_key,
            "provider": provider_name,
            "model": model,
            "seconds": seconds,
            "tokens": {
                "prompt": usage.prompt_tokens if usage else None,
                "completion": usage.completion_tokens if usage else None,
                "total": usage.total_tokens if usage else None,
            },
            "output_text": message.content,
            "output_tool_calls": [tc.function.name for tc in (message.tool_calls or [])],
        })
        return message

    raise AllModelsFailed(f"No model available for role '{role_key}': " + "; ".join(errors))
