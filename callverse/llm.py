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


# Waiting is done through this name so the tests can replace it (no real waiting in tests).
_sleep = time.sleep


def retry_after_seconds(error) -> float | None:
    """The provider's "retry-after" header of a 429 error, in seconds (None if missing or unreadable)."""
    response = getattr(error, "response", None)
    value = response.headers.get("retry-after") if response is not None else None
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def models_for(role_key: str, cfg: dict) -> list[dict]:
    """The models of a role, in order. Env CALLVERSE_FORCE_<ROLE>_MODEL (e.g. CALLVERSE_FORCE_AGENTS_MODEL)
    keeps only the model with that name: used to test one model on its own (e.g. Gemini)."""
    entries = cfg["models"][role_key]
    forced = os.getenv(f"CALLVERSE_FORCE_{role_key.upper()}_MODEL")
    if forced:
        entries = [e for e in entries if e["model"] == forced]
        if not entries:
            raise AllModelsFailed(f"forced model '{forced}' is not in models.{role_key} of config.yaml")
    return entries


def messages_for(provider: dict, messages: list[dict]) -> list[dict]:
    """The messages as this provider accepts them.

    Gemini adds an "extra_content" field (its thought signature) to each tool call and needs it back.
    Other providers may refuse unknown fields, so it is removed for them (config: tool_call_extras).
    """
    if provider.get("tool_call_extras"):
        return messages
    cleaned = []
    for m in messages:
        if m.get("tool_calls"):
            m = {**m, "tool_calls": [{k: v for k, v in tc.items() if k in ("id", "type", "function")}
                                     for tc in m["tool_calls"]]}
        cleaned.append(m)
    return cleaned


def chat(role_key: str, messages: list[dict], tools: list[dict] | None = None):
    """Send `messages` to the first available model of `role_key` and return the reply message.

    - Models are tried in the order of config.yaml (backup chain).
    - Rate limit (429): if the provider says "retry after" <= llm.max_retry_wait_s seconds (config),
      we wait that long and retry the SAME model once (a short wait is cheaper than a weaker model);
      a longer wait, or a second 429, moves on to the next model.
    - We also move on when the problem is on the provider's side:
      model not found (404), server error (5xx) or connection error.
    - We do NOT move on for other errors such as 400 (bad request): that means our request is
      wrong, so another model would fail too and the error must be fixed in our code.
    - A model whose API key is missing in .env is skipped (logged).
    - Provider, model, token usage, time and every wait are written to the trace.
    The returned object has `.content` (text) and `.tool_calls` (None or a list).
    """
    cfg = load_config()
    max_wait = cfg.get("llm", {}).get("max_retry_wait_s", 20)
    errors = []

    for entry in models_for(role_key, cfg):
        provider_name, model = entry["provider"], entry["model"]
        provider = cfg["providers"][provider_name]

        api_key = os.getenv(provider["key_env"])
        if not api_key:
            reason = f"missing {provider['key_env']} in .env"
            trace.log("llm_skip", "llm", {"role": role_key, "provider": provider_name,
                                          "model": model, "reason": reason})
            errors.append(f"{provider_name}/{model}: {reason}")
            continue

        # max_retries=0: we decide ourselves when to wait, retry or move to the next model.
        client = OpenAI(base_url=provider["base_url"], api_key=api_key, max_retries=0, timeout=60)
        # entry "options" = extra request settings of that model in config.yaml (e.g. reasoning_effort).
        request = {"model": model, "messages": messages_for(provider, messages), **entry.get("options", {})}
        if tools:
            request["tools"] = tools

        response = None
        for attempt in (1, 2):
            start = time.perf_counter()
            try:
                response = client.chat.completions.create(**request)
                break
            except RateLimitError as e:
                wait = retry_after_seconds(e)
                if attempt == 1 and wait is not None and wait <= max_wait:
                    trace.log("llm_wait", "llm", {"role": role_key, "provider": provider_name,
                                                  "model": model, "seconds": wait})
                    _sleep(wait)
                    continue
                error = e
            except (NotFoundError, InternalServerError, APIConnectionError) as e:
                error = e
            # 429 (long wait or second time) / 404 / 5xx / network problem: try the next model.
            trace.log("llm_fallback", "llm", {"role": role_key, "provider": provider_name,
                                              "model": model, "error": f"{type(error).__name__}: {error}"})
            errors.append(f"{provider_name}/{model}: {type(error).__name__}")
            break
        if response is None:
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
