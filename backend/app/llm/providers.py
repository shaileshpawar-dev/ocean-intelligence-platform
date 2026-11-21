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


#: Hard ceiling on a narrative call. A demo must not stall on a slow model:
#: past this the caller falls back to the deterministic template, which is
#: always available and always correct.
GEMINI_TIMEOUT_SECONDS = 15.0


class GeminiLLM(_SDKProvider):
    """Google Gemini over the REST ``generateContent`` endpoint.

    Called directly with ``httpx`` rather than through an SDK. The endpoint is
    two fields of JSON, httpx is already a dependency, and the alternative
    (``google-generativeai``) is deprecated in favour of a different package
    again -- a dependency whose name keeps changing is not worth taking on for
    one POST.

    The API key travels as a header, never in the query string, so it cannot
    be captured by proxy or server access logs.
    """

    name = "gemini"
    env_key = "GEMINI_API_KEY"
    default_model = "gemini-3.8-flash"
    base_url = "https://generativelanguage.googleapis.com/v1beta"

    def _load(self) -> Any:
        """No client to construct: availability is just a key being present."""
        if not self.api_key:
            self._error = f"{self.env_key} is not set"
            return None
        return self

    @property
    def is_available(self) -> bool:
        """True when a key is configured. Reachability is proven by calling."""
        return bool(self.api_key)

    def generate(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int = 800,
        temperature: float = 0.2,
    ) -> LLMResponse:
        """Generate text, mapping system turns to ``system_instruction``."""
        if not self.api_key:
            return LLMResponse(
                status=LLMStatus.UNAVAILABLE,
                provider=self.name,
                detail=f"{self.env_key} is not set",
            )

        import httpx

        system = "\n\n".join(m.content for m in messages if m.role == "system")
        turns = [
            {
                "role": "model" if m.role == "assistant" else "user",
                "parts": [{"text": m.content}],
            }
            for m in messages
            if m.role != "system"
        ]
        body: dict[str, Any] = {
            "contents": turns or [{"role": "user", "parts": [{"text": ""}]}],
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }
        if system:
            body["system_instruction"] = {"parts": [{"text": system}]}

        started = time.perf_counter()
        try:
            response = httpx.post(
                f"{self.base_url}/models/{self.model}:generateContent",
                headers={"x-goog-api-key": self.api_key},
                json=body,
                timeout=GEMINI_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            logger.warning("llm_call_failed", extra={"provider": self.name})
            return LLMResponse(
                status=LLMStatus.ERROR,
                provider=self.name,
                model=self.model,
                detail=f"{type(exc).__name__}",
                latency_ms=(time.perf_counter() - started) * 1000,
            )

        latency = (time.perf_counter() - started) * 1000
        if response.status_code != 200:
            logger.warning(
                "llm_call_failed",
                extra={"provider": self.name, "status": response.status_code},
            )
            # The body is not echoed: an API error can quote the request, and
            # the request carries the key.
            return LLMResponse(
                status=LLMStatus.ERROR,
                provider=self.name,
                model=self.model,
                detail=f"HTTP {response.status_code}",
                latency_ms=latency,
            )

        payload = response.json()
        candidates = payload.get("candidates") or []
        text = "".join(
            part.get("text", "")
            for candidate in candidates[:1]
            for part in (candidate.get("content") or {}).get("parts") or []
        ).strip()
        if not text:
            # A truncated or filtered response is a failure, not an empty
            # narrative to be rendered as though the model had nothing to say.
            reason = (candidates[0].get("finishReason") if candidates else None) or "no candidates"
            return LLMResponse(
                status=LLMStatus.ERROR,
                provider=self.name,
                model=self.model,
                detail=f"empty response ({reason})",
                latency_ms=latency,
            )

        usage = payload.get("usageMetadata") or {}
        return LLMResponse(
            status=LLMStatus.OK,
            text=text,
            provider=self.name,
            model=self.model,
            latency_ms=latency,
            usage={
                "prompt": usage.get("promptTokenCount", 0),
                "completion": usage.get("candidatesTokenCount", 0),
            },
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
        # llm_model overrides for any provider; gemini_model is the
        # per-provider default, resolved from the live model list rather than
        # hardcoded to an id Google may have retired.
        model = settings.llm_model
        if provider_name == "gemini" and not model:
            model = settings.gemini_model
        candidate = _PROVIDERS[provider_name](key, model)
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
