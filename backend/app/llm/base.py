"""LLM provider abstraction.

Design rules, in priority order:

1. **The platform must run with no LLM at all.** ``LLM_PROVIDER=none`` is the
   default. Every feature that uses a model degrades to a deterministic,
   template-based path rather than disappearing. An interview demo must not
   depend on an API key.
2. **A model never produces a number the system can compute.** Risk scores,
   confidences, areas and forecasts come from the deterministic engines. The
   LLM's job is to *explain* those values in prose and to synthesise retrieved
   text. :class:`BaseLLM` therefore has no "score this" method.
3. **Chain-of-thought is never stored or exposed.** Agents persist a concise
   ``reasoning_summary`` plus the evidence they used, which is what makes a
   run auditable. Raw reasoning traces are not requested and not kept.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class LLMStatus(StrEnum):
    """Outcome of a generation call."""

    OK = "ok"
    UNAVAILABLE = "unavailable"
    """No provider configured, or its SDK/credentials are missing."""

    ERROR = "error"
    """The provider was reachable but the call failed."""


@dataclass(slots=True)
class LLMMessage:
    """One turn in a prompt."""

    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass(slots=True)
class LLMResponse:
    """A generation result, including the honest failure cases.

    ``status`` is checked by every caller. A caller that ignores it and reads
    ``text`` on an unavailable provider gets an empty string, never a
    plausible-looking fabrication.
    """

    status: LLMStatus
    text: str = ""
    provider: str = "none"
    model: str | None = None
    #: Parsed object when the call requested structured output.
    data: dict[str, Any] | None = None
    latency_ms: float | None = None
    detail: str | None = None
    #: Token counts when the provider reports them.
    usage: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """True when usable text or data came back."""
        return self.status is LLMStatus.OK

    def to_dict(self) -> dict[str, Any]:
        """Serialise for storage on an agent run."""
        payload = asdict(self)
        payload["status"] = str(self.status)
        return payload


class BaseLLM(ABC):
    """Interface every LLM provider implements.

    Deliberately narrow. Providers generate text or a JSON object from
    messages; they do not own prompts, tools, retries or business logic.
    """

    name: str = "base"

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Whether this provider can serve a request right now."""

    @abstractmethod
    def generate(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int = 800,
        temperature: float = 0.2,
    ) -> LLMResponse:
        """Produce free text from a message list."""

    def generate_structured(
        self,
        messages: list[LLMMessage],
        schema: dict[str, Any],
        *,
        max_tokens: int = 800,
    ) -> LLMResponse:
        """Produce a JSON object conforming to ``schema``.

        The default implementation asks for JSON in the prompt and parses the
        reply, which works across providers. A provider with native structured
        output should override this.
        """
        import json

        instruction = (
            "Reply with a single JSON object and nothing else. No prose, no "
            "code fences. It must match this JSON schema:\n"
            f"{json.dumps(schema, indent=2)}"
        )
        augmented = [*messages, LLMMessage(role="user", content=instruction)]
        response = self.generate(augmented, max_tokens=max_tokens, temperature=0.0)
        if not response.ok:
            return response

        response.data = _extract_json(response.text)
        if response.data is None:
            response.status = LLMStatus.ERROR
            response.detail = "provider did not return parseable JSON"
        return response

    def describe(self) -> dict[str, Any]:
        """Provider metadata for /health and agent-run records."""
        return {"provider": self.name, "available": self.is_available}


def _extract_json(text: str) -> dict[str, Any] | None:
    """Best-effort JSON object extraction from a model reply.

    Tolerates code fences and leading prose, because providers add them even
    when told not to. Returns ``None`` rather than guessing at a repair.
    """
    import json

    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.split("```")[1] if "```" in candidate[3:] else candidate
        candidate = candidate.removeprefix("json").strip()

    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    start, depth = candidate.find("{"), 0
    if start < 0:
        return None
    for index in range(start, len(candidate)):
        if candidate[index] == "{":
            depth += 1
        elif candidate[index] == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(candidate[start : index + 1])
                    return parsed if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    return None
    return None
