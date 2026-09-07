"""Concrete LLM providers, all optional.

Each provider imports its SDK lazily inside ``is_available`` so a missing
dependency degrades the platform rather than breaking start-up.
"""

from __future__ import annotations

import time
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.llm.base import BaseLLM, LLMMessage, LLMResponse, LLMStatus

logger = get_logger(__name__)


class NullLLM(BaseLLM):
    """The default provider: refuses, clearly, and never fabricates.

    Returning ``UNAVAILABLE`` rather than raising lets every caller keep its
    deterministic path. This is the provider an interview demo runs on.
    """

    name = "none"

    @property
    def is_available(self) -> bool:
        """Always false. That is the point."""
        return False

    def generate(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int = 800,
        temperature: float = 0.2,
    ) -> LLMResponse:
        """Return an explicit unavailability, never invented text."""
        return LLMResponse(
            status=LLMStatus.UNAVAILABLE,
            provider=self.name,
            detail=(
                "No LLM provider configured. Set LLM_PROVIDER (gemini | openai | "
                "anthropic) and the matching API key. Narrative generation is "
                "optional: every figure in this platform is computed "
                "deterministically and rendered from templates without a model."
            ),
        )


class _SDKProvider(BaseLLM):
    """Shared plumbing for SDK-backed providers."""

    env_key: str = ""
    default_model: str = ""

    def __init__(self, api_key: str | None, model: str | None) -> None:
        """Store credentials; the SDK is imported on first use."""
        self.api_key = api_key
        self.model = model or self.default_model
        self._client: Any = None
        self._error: str | None = None

    def _load(self) -> Any:
        raise NotImplementedError

    @property
    def is_available(self) -> bool:
        """True when an API key is present and the SDK imports."""
        if not self.api_key:
            self._error = f"{self.env_key} is not set"
            return False
        return self._load() is not None

    def describe(self) -> dict[str, Any]:
        """Provider metadata including the configured model."""
        info = super().describe()
        info["model"] = self.model
        if self._error:
            info["detail"] = self._error
        return info


class GeminiLLM(_SDKProvider):
    """Google Gemini via ``google-generativeai``."""

    name = "gemini"
    env_key = "GEMINI_API_KEY"
    default_model = "gemini-2.0-flash"

    def _load(self) -> Any:
        if self._client is not None or self._error:
            return self._client
        try:
            import google.generativeai as genai

            genai.configure(api_key=self.api_key)
            self._client = genai.GenerativeModel(self.model)
        except Exception as exc:
            self._error = f"{type(exc).__name__}: {exc}"
            logger.warning("llm_unavailable", extra={"provider": self.name})
        return self._client

    def generate(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int = 800,
        temperature: float = 0.2,
    ) -> LLMResponse:
        """Generate text, flattening the message list into Gemini's format."""
        client = self._load()
        if client is None:
            return LLMResponse(
                status=LLMStatus.UNAVAILABLE, provider=self.name, detail=self._error
            )
        started = time.perf_counter()
        try:
            prompt = "\n\n".join(f"[{m.role}] {m.content}" for m in messages)
            result = client.generate_content(
                prompt,
                generation_config={
                    "max_output_tokens": max_tokens,
                    "temperature": temperature,
                },
            )
            return LLMResponse(
                status=LLMStatus.OK,
                text=(result.text or "").strip(),
                provider=self.name,
                model=self.model,
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        except Exception as exc:
            logger.warning("llm_call_failed", extra={"provider": self.name})
            return LLMResponse(
                status=LLMStatus.ERROR,
                provider=self.name,
                model=self.model,
                detail=f"{type(exc).__name__}: {exc}",
            )


class OpenAILLM(_SDKProvider):
    """OpenAI chat completions."""

    name = "openai"
    env_key = "OPENAI_API_KEY"
    default_model = "gpt-4o-mini"

    def _load(self) -> Any:
        if self._client is not None or self._error:
            return self._client
        try:
            from openai import OpenAI

            self._client = OpenAI(api_key=self.api_key)
        except Exception as exc:
            self._error = f"{type(exc).__name__}: {exc}"
            logger.warning("llm_unavailable", extra={"provider": self.name})
        return self._client

    def generate(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int = 800,
        temperature: float = 0.2,
    ) -> LLMResponse:
        """Generate text through the chat completions API."""
        client = self._load()
        if client is None:
            return LLMResponse(
                status=LLMStatus.UNAVAILABLE, provider=self.name, detail=self._error
            )
        started = time.perf_counter()
        try:
            result = client.chat.completions.create(
                model=self.model,
                messages=[{"role": m.role, "content": m.content} for m in messages],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            usage = getattr(result, "usage", None)
            return LLMResponse(
                status=LLMStatus.OK,
                text=(result.choices[0].message.content or "").strip(),
                provider=self.name,
                model=self.model,
                latency_ms=(time.perf_counter() - started) * 1000,
                usage=(
                    {
                        "prompt": usage.prompt_tokens,
                        "completion": usage.completion_tokens,
                    }
                    if usage
                    else {}
                ),
            )
        except Exception as exc:
            logger.warning("llm_call_failed", extra={"provider": self.name})
            return LLMResponse(
                status=LLMStatus.ERROR,
                provider=self.name,
                model=self.model,
                detail=f"{type(exc).__name__}: {exc}",
            )


class AnthropicLLM(_SDKProvider):
    """Anthropic Claude via the Messages API."""

    name = "anthropic"
    env_key = "ANTHROPIC_API_KEY"
    default_model = "claude-sonnet-4-5"

    def _load(self) -> Any:
        if self._client is not None or self._error:
            return self._client
        try:
            import anthropic

            self._client = anthropic.Anthropic(api_key=self.api_key)
        except Exception as exc:
            self._error = f"{type(exc).__name__}: {exc}"
            logger.warning("llm_unavailable", extra={"provider": self.name})
        return self._client

    def generate(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int = 800,
        temperature: float = 0.2,
    ) -> LLMResponse:
        """Generate text, hoisting system turns into the system parameter."""
        client = self._load()
        if client is None:
            return LLMResponse(
                status=LLMStatus.UNAVAILABLE, provider=self.name, detail=self._error
            )
        started = time.perf_counter()
        try:
            system = "\n\n".join(m.content for m in messages if m.role == "system")
            turns = [
                {"role": m.role, "content": m.content}
                for m in messages
                if m.role != "system"
            ]
            result = client.messages.create(
                model=self.model,
                system=system or None,
                messages=turns or [{"role": "user", "content": ""}],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            text = "".join(
                block.text for block in result.content if hasattr(block, "text")
            )
            return LLMResponse(
                status=LLMStatus.OK,
                text=text.strip(),
                provider=self.name,
                model=self.model,
                latency_ms=(time.perf_counter() - started) * 1000,
                usage={
                    "prompt": result.usage.input_tokens,
                    "completion": result.usage.output_tokens,
                },
            )
        except Exception as exc:
            logger.warning("llm_call_failed", extra={"provider": self.name})
            return LLMResponse(
                status=LLMStatus.ERROR,
                provider=self.name,
                model=self.model,
                detail=f"{type(exc).__name__}: {exc}",
            )


_PROVIDERS: dict[str, type[_SDKProvider]] = {
    "gemini": GeminiLLM,
    "openai": OpenAILLM,
    "anthropic": AnthropicLLM,
}

_llm: BaseLLM | None = None


def get_llm(force: str | None = None) -> BaseLLM:
    """Return the configured LLM provider.

    Falls back to :class:`NullLLM` when the configured provider has no key or
    its SDK is missing, so the platform never fails to start over an optional
    narrative feature.
    """
    global _llm
    if _llm is not None and force is None:
        return _llm

    provider_name = force or settings.llm_provider
    provider: BaseLLM
    if provider_name in _PROVIDERS:
        key = {
            "gemini": settings.gemini_api_key,
            "openai": settings.openai_api_key,
            "anthropic": settings.anthropic_api_key,
        }[provider_name]
        candidate = _PROVIDERS[provider_name](key, settings.llm_model)
        if candidate.is_available:
            provider = candidate
        else:
            logger.info("llm_fallback_to_null", extra={"requested": provider_name})
            provider = NullLLM()
    else:
        provider = NullLLM()

    if force is None:
        _llm = provider
    return provider


def reset_llm() -> None:
    """Clear the cached provider. Used between tests."""
    global _llm
    _llm = None
