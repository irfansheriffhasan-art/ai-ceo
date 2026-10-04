"""Provider-neutral LLM types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMRequest:
    system: str
    prompt: str
    model: str
    json_schema: dict[str, Any] | None = None
    max_tokens: int = 2048
    temperature: float = 0.2
    purpose: str = ""
    # "role:purpose" routing key; used by the mock provider and in traces.
    tag: str = ""
    # Called with the approximate number of output tokens generated so far.
    on_progress: Callable[[int], None] | None = field(default=None, repr=False)


@dataclass
class LLMResponse:
    text: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0
    truncated: bool = False


class LLMError(Exception):
    """A failed model call. ``retryable`` tells the client whether to try again."""

    def __init__(self, message: str, *, retryable: bool = True, hint: str = ""):
        super().__init__(message)
        self.retryable = retryable
        self.hint = hint

    def __str__(self) -> str:
        base = super().__str__()
        return f"{base} ({self.hint})" if self.hint else base


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def complete(self, req: LLMRequest) -> LLMResponse: ...

    @abstractmethod
    async def health(self) -> dict[str, Any]:
        """Return ``{"ok": bool, "detail": str, ...}`` without raising."""

    async def aclose(self) -> None:  # pragma: no cover - optional
        return None
