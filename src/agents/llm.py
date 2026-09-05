"""One place where an LLM client is constructed.

Every agent calls ``get_llm()``. Nothing else instantiates a provider client. That
buys three things the project needs by Week 6:

* **Provider swap is a `.env` edit.** Free tiers change and rate-limit; when Gemini
  starts refusing, `LLM_PROVIDER=ollama` moves five agents at once.
* **Fallback is automatic.** ``get_llm(with_fallback=True)`` returns a chain that
  fails over on a provider error rather than dropping an evaluation run.
* **Traces have one shape.** Week 7's monitoring page reads one log format because
  there is one call site.
"""

from __future__ import annotations

import os
from functools import lru_cache

from langchain_core.language_models.chat_models import BaseChatModel

from src.common import config
from src.common.logging_setup import get_logger

log = get_logger("agents.llm")

#: Sensible default model per provider. Override per call or via LLM_MODEL in .env.
#: `gemini-2.0-flash` (the original Week 1 pin) was retired by Google during Week 4 —
#: the API's own 404 names its replacement. Free-tier model names are not a stable
#: foundation to build five weeks of agents on; see P-35.
DEFAULT_MODELS = {
    "gemini": "gemini-3.6-flash",
    "anthropic": "claude-sonnet-5",
    "ollama": "llama3.1:8b",
}

#: Which env var must be set for each provider. Ollama needs a running host, not a key.
REQUIRED_KEY = {
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "ollama": None,
}


class LLMNotConfigured(RuntimeError):
    """Raised when the selected provider has no usable credentials."""


def available_providers() -> list[str]:
    """Providers that could actually be called right now, in preference order."""
    out = []
    for name, var in REQUIRED_KEY.items():
        if var is None:
            continue  # ollama presence is only knowable by calling it
        if os.environ.get(var):
            out.append(name)
    return out


def _build(provider: str, model: str, temperature: float) -> BaseChatModel:
    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise LLMNotConfigured("GEMINI_API_KEY is not set — copy .env.example to .env")
        return ChatGoogleGenerativeAI(model=model, temperature=temperature, google_api_key=key)

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise LLMNotConfigured("ANTHROPIC_API_KEY is not set — copy .env.example to .env")
        return ChatAnthropic(model=model, temperature=temperature, api_key=key)

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=model,
            temperature=temperature,
            base_url=os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
        )

    raise LLMNotConfigured(
        f"Unknown LLM_PROVIDER {provider!r}. Expected one of {sorted(DEFAULT_MODELS)}."
    )


@lru_cache(maxsize=8)
def get_llm(
    provider: str | None = None,
    model: str | None = None,
    temperature: float = 0.0,
    with_fallback: bool = False,
) -> BaseChatModel:
    """Return a chat model.

    Args:
        provider: gemini / anthropic / ollama. Defaults to ``LLM_PROVIDER``.
        model: provider-specific model id. Defaults to ``LLM_MODEL`` then to
            ``DEFAULT_MODELS[provider]``.
        temperature: 0.0 by default. Extraction and audit agents must stay
            deterministic; only the customer-notification drafting raises it.
        with_fallback: chain the other configured providers behind this one, so a
            rate-limited free tier does not abort an evaluation run.
    """
    provider = (provider or config.LLM_PROVIDER).lower()
    model = model or os.environ.get("LLM_MODEL") or DEFAULT_MODELS.get(provider, "")

    primary = _build(provider, model, temperature)
    if not with_fallback:
        return primary

    others = [p for p in available_providers() if p != provider]
    if not others:
        log.warning(
            "with_fallback=True but %s is the only configured provider — "
            "add a second key to .env before the Week 7 evaluation runs.",
            provider,
        )
        return primary

    backups = [_build(p, DEFAULT_MODELS[p], temperature) for p in others]
    log.info("LLM: %s with fallback to %s", provider, ", ".join(others))
    return primary.with_fallbacks(backups)


def describe() -> str:
    """One-line summary of the current LLM configuration, for logs and the dashboard."""
    configured = available_providers()
    return (
        f"provider={config.LLM_PROVIDER} "
        f"model={os.environ.get('LLM_MODEL') or DEFAULT_MODELS.get(config.LLM_PROVIDER, '?')} "
        f"configured={configured or ['none']}"
    )
