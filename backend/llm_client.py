"""
llm_client.py — Local LLM integration
Owner: Srivatsav (Backend & Agent Orchestration)

WHAT THIS DOES
--------------
Wraps calls to a locally-hosted Ollama model (e.g. llama3.2:3b). This is the
real integration your laptop will use — if Ollama is installed and running
on localhost:11434, every agent call below genuinely goes through a local
LLM with real generative reasoning.

GRACEFUL FALLBACK
------------------
If Ollama isn't reachable (e.g. this review environment, or a teammate's
laptop before they've installed it), calls fall back to a deterministic
template response so the rest of the pipeline can still be developed,
tested, and demoed without blocking on every teammate having Ollama set up
locally. This is standard practice for team development against an external
dependency — not a shortcut in the final product.

TO RUN WITH A REAL LLM
------------------------
1. Install Ollama: https://ollama.com
2. Pull a model:     ollama pull llama3.2:3b
3. Start the server:  ollama serve   (usually runs automatically)
4. Nothing else changes — this client will detect it and use it.
"""

import contextvars
import json
import httpx

from backend import config

OLLAMA_URL = config.OLLAMA_CHAT_URL
DEFAULT_MODEL = config.OLLAMA_MODEL


_ai_state = contextvars.ContextVar("ai_state", default=None)


def reset_ai_state() -> None:
    """Start tracking AI usage for the current request."""
    _ai_state.set({"live": 0, "fallback": 0, "reason": None})


def _note(kind: str, reason: str = None) -> None:
    st = _ai_state.get()
    if st is not None:
        st[kind] += 1
        if reason and not st["reason"]:
            st["reason"] = reason


def ai_mode() -> dict:
    """What actually produced this request's wording: the live model, built-in rules, or a mix."""
    st = _ai_state.get() or {"live": 0, "fallback": 0, "reason": None}
    if st["live"] and not st["fallback"]:
        return {"ai_mode": "live_model", "ai_note": None}
    if st["live"] and st["fallback"]:
        return {"ai_mode": "mixed", "ai_note": "Part of the wording came from built-in rules because the AI model was slow or unavailable."}
    why = {"model_not_running": "The AI model is not running, so built-in rules were used.",
           "model_call_failed": "The AI model did not answer in time or returned an error, so built-in rules were used."}
    return {"ai_mode": "built_in_rules", "ai_note": why.get(st["reason"], "Built-in rules were used.")}


class OllamaUnavailable(Exception):
    pass


def _check_ollama_alive(timeout: float = 1.0) -> bool:
    try:
        r = httpx.get(config.OLLAMA_BASE_URL, timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def is_ollama_live() -> bool:
    """
    Re-checks connectivity on every call rather than caching a single
    startup-time result. This matters for live demos specifically: if
    Ollama gets started *after* the backend server is already running,
    the system picks it up on the very next request instead of needing a
    full server restart.
    """
    return _check_ollama_alive()


# Kept for any code that still imports the old cached constant directly;
# prefer is_ollama_live() in new code since it re-checks live.
OLLAMA_LIVE = _check_ollama_alive()


def call_llm(prompt: str, model: str = DEFAULT_MODEL, fallback_fn=None) -> str:
    """
    Sends `prompt` to the local Ollama model and returns the raw text response.
    If Ollama is unreachable, uses `fallback_fn` (a zero-arg callable returning
    a string) if provided, else raises OllamaUnavailable.
    """
    if is_ollama_live():
        try:
            with httpx.Client(timeout=config.OLLAMA_TIMEOUT) as client:
                resp = client.post(
                    OLLAMA_URL,
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": False,
                    },
                )
                resp.raise_for_status()
                out = resp.json()["message"]["content"]
                _note("live")
                return out
        except Exception as e:
            print(f"[llm_client] Ollama call failed ({type(e).__name__}), using fallback.")
            _note("fallback", "model_call_failed")
    else:
        _note("fallback", "model_not_running")

    if fallback_fn is not None:
        return fallback_fn()
    raise OllamaUnavailable(
        f"Ollama is not running at {config.OLLAMA_BASE_URL} and no fallback was provided. "
        "Install and start Ollama, or pass a fallback_fn."
    )


def parse_json_response(raw: str) -> dict:
    """
    LLMs sometimes wrap JSON in markdown fences or add stray text.
    This strips common wrapping and attempts to parse safely.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
        return {"error": "could not parse LLM response as JSON", "raw": raw}
