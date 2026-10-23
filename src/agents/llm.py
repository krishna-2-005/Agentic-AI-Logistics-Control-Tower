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
import time
from functools import lru_cache

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import SecretStr

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
    # Open-weight model on Groq's free tier, used by the B7 ablation (D-086) because the
    # Gemini free tier cannot afford ~1,000 calls. Not the model that writes the prose.
    "groq": "openai/gpt-oss-120b",
}

#: Every provider call gets a wall-clock ceiling and a bounded retry count. Without them
#: a single stalled request hangs its caller indefinitely: in Week 7 one document
#: extraction sat for twenty minutes with no error, while the client's own retry loop
#: quietly spent the rest of the day's 20-call free tier (P-53). A call that cannot
#: finish in two minutes should fail loudly, so a resumable evaluation can stop and pick
#: up tomorrow instead of burning quota on a request nobody is waiting for.
REQUEST_TIMEOUT_S = 120
MAX_RETRIES = 2

#: Which env var must be set for each provider. Ollama needs a running host, not a key.
REQUIRED_KEY = {
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "ollama": None,
    "groq": "GROQ_API_KEY",
}


class LLMNotConfigured(RuntimeError):
    """Raised when the selected provider has no usable credentials."""


GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class ProviderRateLimited(RuntimeError):
    """The provider kept answering 429 after the allowed waits (a daily cap, usually)."""


class GroqChat(BaseChatModel):
    """Groq's OpenAI-compatible chat endpoint over httpx, as a langchain chat model.

    Written directly instead of adding a dependency: it needs one POST. A 429 is waited out
    using the provider's own ``retry-after`` (capped), then retried a bounded number of
    times; a wait the provider says is longer than ``max_wait_s`` raises
    :class:`ProviderRateLimited` instead of sleeping for hours.
    """

    model: str
    api_key: SecretStr
    temperature: float = 0.0
    reasoning_effort: str | None = "low"
    max_tokens: int = 600
    timeout_s: float = REQUEST_TIMEOUT_S
    max_attempts: int = 6
    max_wait_s: float = 90.0

    @property
    def _llm_type(self) -> str:
        return "groq-httpx"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[no-untyped-def]
        payload: dict = {
            "model": self.model,
            "messages": [{"role": "user", "content": m.content} for m in messages],
            "temperature": self.temperature,
            "max_completion_tokens": self.max_tokens,
        }
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        headers = {"Authorization": f"Bearer {self.api_key.get_secret_value()}"}
        last = ""
        for attempt in range(self.max_attempts):
            response = httpx.post(GROQ_URL, json=payload, headers=headers, timeout=self.timeout_s)
            if response.status_code == 429 or response.status_code >= 500:
                last = f"HTTP {response.status_code}"
                wait = _retry_after_s(response, attempt)
                if wait > self.max_wait_s:
                    raise ProviderRateLimited(f"{last}; provider asks for a {wait:.0f}s wait")
                time.sleep(wait)
                continue
            response.raise_for_status()
            body = response.json()
            usage = body.get("usage", {})
            message = AIMessage(
                content=body["choices"][0]["message"].get("content") or "",
                usage_metadata={
                    "input_tokens": int(usage.get("prompt_tokens", 0)),
                    "output_tokens": int(usage.get("completion_tokens", 0)),
                    "total_tokens": int(usage.get("total_tokens", 0)),
                },
            )
            return ChatResult(generations=[ChatGeneration(message=message)])
        raise ProviderRateLimited(f"{last} after {self.max_attempts} attempts")


def _retry_after_s(response: httpx.Response, attempt: int) -> float:
    """Seconds to wait before retrying: the provider's hint if present, else backoff."""
    header = response.headers.get("retry-after")
    if header:
        try:
            return float(header) + 0.5
        except ValueError:
            pass
    return min(2.0 * 2**attempt, 60.0)


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
        return ChatGoogleGenerativeAI(
            model=model, temperature=temperature, google_api_key=key,
            timeout=REQUEST_TIMEOUT_S, max_retries=MAX_RETRIES,
        )

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise LLMNotConfigured("ANTHROPIC_API_KEY is not set — copy .env.example to .env")
        # The key is wrapped rather than passed as a str. Pydantic would coerce
        # it either way, but SecretStr is what the field is declared as and it
        # keeps the key out of a repr -- these objects end up in tracebacks.
        #
        # `model=` keeps the ignore: mypy reads pydantic's generated __init__,
        # which is keyed on the aliases (`model_name`), and does not model
        # populate_by_name. Checked against the installed package rather than
        # assumed -- both forms construct. Left as `model=` because rewriting an
        # untested fallback path to satisfy a checker is how a fallback quietly
        # stops working.
        return ChatAnthropic(  # type: ignore[call-arg]
            model=model, temperature=temperature, api_key=SecretStr(key),
            timeout=REQUEST_TIMEOUT_S, max_retries=MAX_RETRIES,
        )

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=model,
            temperature=temperature,
            base_url=os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
        )

    if provider == "groq":
        key = os.environ.get("GROQ_API_KEY")
        if not key:
            raise LLMNotConfigured("GROQ_API_KEY is not set")
        return GroqChat(model=model, api_key=SecretStr(key), temperature=temperature)

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
    return primary.with_fallbacks(backups)  # type: ignore[return-value]  # with_fallbacks returns a RunnableWithFallbacks; it is a chat model at runtime and langchain does not express that


def describe() -> str:
    """One-line summary of the current LLM configuration, for logs and the dashboard."""
    configured = available_providers()
    return (
        f"provider={config.LLM_PROVIDER} "
        f"model={os.environ.get('LLM_MODEL') or DEFAULT_MODELS.get(config.LLM_PROVIDER, '?')} "
        f"configured={configured or ['none']}"
    )
