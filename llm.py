"""Free-tier LLM client over OpenAI-compatible endpoints.

Tries providers in order and falls through on errors or rate limits:
  1. Google Gemini (GEMINI_API_KEY, free key from aistudio.google.com)
  2. GitHub Models (GITHUB_TOKEN, free inside GitHub Actions, small context)
  3. Groq (GROQ_API_KEY, optional)
"""

import json
import os
import re
import time
from collections.abc import Callable
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class LLMError(Exception):
    pass


def _models(env_var: str, default: str) -> list[str]:
    return [m.strip() for m in os.environ.get(env_var, default).split(",") if m.strip()]


def _providers() -> list[dict]:
    providers = []
    if os.environ.get("GEMINI_API_KEY"):
        providers.append({
            "name": "gemini",
            "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
            "key": os.environ["GEMINI_API_KEY"],
            "models": _models("GEMINI_MODELS", "gemini-flash-latest,gemini-flash-lite-latest"),
            "max_chars": 300_000,
        })
    if os.environ.get("GITHUB_TOKEN"):
        providers.append({
            "name": "github",
            "url": "https://models.github.ai/inference/chat/completions",
            "key": os.environ["GITHUB_TOKEN"],
            "models": _models("GITHUB_MODELS", "openai/gpt-4.1-mini"),
            "max_chars": 22_000,
        })
    if os.environ.get("GROQ_API_KEY"):
        providers.append({
            "name": "groq",
            "url": "https://api.groq.com/openai/v1/chat/completions",
            "key": os.environ["GROQ_API_KEY"],
            "models": _models("GROQ_MODELS", "llama-3.3-70b-versatile"),
            "max_chars": 18_000,
        })
    return providers


def available() -> bool:
    return bool(_providers())


def _parse_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def _post(provider: dict, model: str, system: str, user: str) -> dict:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.4,
        "response_format": {"type": "json_object"},
    }).encode()
    req = Request(provider["url"], data=body, headers={
        "Authorization": f"Bearer {provider['key']}",
        "Content-Type": "application/json",
    })
    with urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read())
    content = data["choices"][0]["message"]["content"]
    if not content:
        raise LLMError("empty response")
    return _parse_json(content)


def json_call(system: str, build_user: Callable[[int], str]) -> dict:
    """build_user(max_chars) returns the user prompt sized for the provider's context."""
    errors = []
    for provider in _providers():
        user = build_user(provider["max_chars"])
        for model in provider["models"]:
            for attempt in range(3):
                try:
                    result = _post(provider, model, system, user)
                    print(f"  LLM ok: {provider['name']}/{model}")
                    return result
                except HTTPError as e:
                    detail = e.read().decode(errors="ignore")[:200]
                    errors.append(f"{provider['name']}/{model}: HTTP {e.code} {detail}")
                    if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                        time.sleep(10 * (attempt + 1))
                        continue
                    break
                except Exception as e:
                    errors.append(f"{provider['name']}/{model}: {type(e).__name__}: {str(e)[:200]}")
                    break
    raise LLMError("All LLM providers failed:\n  " + "\n  ".join(errors or ["no provider configured"]))
